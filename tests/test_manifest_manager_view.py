"""The Image Service Manager's write actions require Resource Editor or Resource Reviewer.

The project view answers Arches' ``manifest_manager`` route; its ``post`` and
``delete`` accept Resource Editor, Resource Reviewer and superusers only.

Usage:
    python manage.py test tests.test_manifest_manager_view --settings="tests.test_settings"
"""

import hashlib
import inspect
import io
import json
import os
import shutil
import textwrap
import tempfile
import uuid
from unittest import mock

from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import (
    Client,
    RequestFactory,
    SimpleTestCase,
    TestCase,
    override_settings,
)
from django.urls import resolve, reverse
from django.utils import translation
from PIL import Image

from arches.app.models import models
from arches.app.views.manifest_manager import (
    ManifestManagerView as CoreManifestManagerView,
)

from manuspectrum.utils import jp2_profile
from manuspectrum.views.manifest_manager import ManifestManagerView

URL = "/en/image-service-manager"
WRITE_GROUPS = {"Resource Editor", "Resource Reviewer"}

# 1×1 transparent PNG.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def pin_language(test, language="en"):
    """Activate *language* for one test; a class decorator would hide the tests."""
    override = translation.override(language)
    override.__enter__()
    test.addCleanup(override.__exit__, None, None, None)


def make_manifest(label="t"):
    uid = uuid.uuid4()
    return models.IIIFManifest.objects.create(
        label=label,
        url=f"/manifest/{uid}",
        globalid=uid,
        manifest={"label": label, "sequences": [{"canvases": []}]},
    )


class ManifestManagerRoutingTests(SimpleTestCase):
    def setUp(self):
        pin_language(self)

    def test_the_route_reaches_the_project_view(self):
        match = resolve(URL)

        self.assertIs(match.func.view_class, ManifestManagerView)
        self.assertEqual(match.url_name, "manifest_manager")

    def test_the_french_url_reaches_it_too(self):
        with translation.override("fr"):
            match = resolve("/fr/image-service-manager")

        self.assertIs(match.func.view_class, ManifestManagerView)
        self.assertEqual(match.url_name, "manifest_manager")

    def test_reversal_still_builds_the_core_url(self):
        self.assertEqual(reverse("manifest_manager"), URL)


class GetUntouchedTests(SimpleTestCase):
    def test_only_the_writes_are_redefined(self):
        self.assertEqual(
            set(ManifestManagerView.__dict__) & {"get", "post", "delete", "dispatch"},
            {"post", "delete"},
        )


class WriteGroupsTests(TestCase):
    """Which accounts the guard lets through, read off the view itself."""

    def setUp(self):
        self.factory = RequestFactory()

    def reaches_core_body(self, user):
        request = self.factory.delete(
            URL,
            data=json.dumps({"manifest": "/manifest/unknown"}),
            content_type="application/json",
        )
        request.user = user
        try:
            ManifestManagerView.as_view()(request)
        except models.IIIFManifest.DoesNotExist:
            return True
        except PermissionDenied:
            return False
        self.fail("the view answered without reaching the guard or the core body")

    def test_exactly_editor_and_reviewer_groups_are_allowed(self):
        allowed = set()
        for group in Group.objects.all():
            user = User.objects.create_user(f"member-{group.pk}")
            user.groups.add(group)
            if self.reaches_core_body(user):
                allowed.add(group.name)

        self.assertEqual(allowed, WRITE_GROUPS)

    def test_the_anonymous_account_is_refused(self):
        anonymous = User.objects.get(username="anonymous")

        self.assertFalse(anonymous.groups.filter(name__in=WRITE_GROUPS).exists())
        self.assertFalse(self.reaches_core_body(anonymous))

    def test_an_unauthenticated_user_is_refused(self):
        self.assertFalse(self.reaches_core_body(AnonymousUser()))

    def test_a_superuser_is_allowed(self):
        admin = User.objects.create_superuser("isadmin", password="pw")

        self.assertTrue(self.reaches_core_body(admin))


class ManifestManagerWriteTests(TestCase):
    """Writes through the full middleware stack: a bare client is ``anonymous``."""

    @classmethod
    def setUpTestData(cls):
        def user(name, *groups, superuser=False):
            if superuser:
                account = User.objects.create_superuser(name, password="pw")
            else:
                account = User.objects.create_user(name, password="pw")
            account.groups.add(*Group.objects.filter(name__in=groups))
            return account

        cls.guest = user("ism-guest", "Guest")
        cls.exporter = user("ism-exporter", "Guest", "Resource Exporter")
        cls.editor = user("ism-editor", "Resource Editor")
        cls.reviewer = user("ism-reviewer", "Resource Reviewer")
        cls.admin = user("ism-admin", superuser=True)

    def setUp(self):
        pin_language(self)
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        media = override_settings(MEDIA_ROOT=self.media_root)
        media.enable()
        self.addCleanup(media.disable)
        fetch = mock.patch.object(
            CoreManifestManagerView,
            "fetch",
            return_value={"width": 10, "height": 10},
        )
        fetch.start()
        self.addCleanup(fetch.stop)

    def refused(self):
        return [None, self.guest, self.exporter]

    def allowed(self):
        return [self.editor, self.reviewer, self.admin]

    def sign_in(self, user):
        self.client.logout()
        if user is not None:
            self.client.force_login(user)

    def create(self):
        upload = SimpleUploadedFile("folio.png", PNG, content_type="image/png")
        return self.client.post(
            URL,
            data={"operation": "create", "manifest_title": "Folio", "files": [upload]},
        )

    def update(self, manifest):
        return self.client.post(
            URL, data={"manifest": manifest.url, "manifest_title": "New"}
        )

    def delete(self, manifest):
        return self.client.delete(
            URL,
            data=json.dumps({"manifest": manifest.url}),
            content_type="application/json",
        )

    def media_files(self):
        return [files for _, _, files in os.walk(self.media_root) if files]

    def test_refused_accounts_cannot_create(self):
        for user in self.refused():
            with self.subTest(user=user):
                self.sign_in(user)
                response = self.create()

                self.assertEqual(response.status_code, 403)
                self.assertFalse(models.IIIFManifest.objects.exists())
                self.assertFalse(models.File.objects.exists())
                self.assertEqual(self.media_files(), [])

    def test_refused_accounts_cannot_update(self):
        manifest = make_manifest()
        for user in self.refused():
            with self.subTest(user=user):
                self.sign_in(user)
                response = self.update(manifest)

                self.assertEqual(response.status_code, 403)
                manifest.refresh_from_db()
                self.assertEqual(manifest.label, "t")

    def test_refused_accounts_cannot_delete(self):
        manifest = make_manifest()
        for user in self.refused():
            with self.subTest(user=user):
                self.sign_in(user)
                response = self.delete(manifest)

                self.assertEqual(response.status_code, 403)
                self.assertTrue(
                    models.IIIFManifest.objects.filter(pk=manifest.pk).exists()
                )

    def test_writes_still_check_the_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.editor)
        manifest = make_manifest()

        response = client.post(
            URL, data={"manifest": manifest.url, "manifest_title": "New"}
        )

        self.assertEqual(response.status_code, 403)
        manifest.refresh_from_db()
        self.assertEqual(manifest.label, "t")

    def test_allowed_accounts_create(self):
        for user in self.allowed():
            with self.subTest(user=user):
                self.sign_in(user)
                before = models.IIIFManifest.objects.count()
                response = self.create()

                self.assertEqual(response.status_code, 200)
                self.assertEqual(models.IIIFManifest.objects.count(), before + 1)
                self.assertEqual(json.loads(response.content)["label"], "Folio")
        self.assertEqual(models.File.objects.count(), len(self.allowed()))
        self.assertNotEqual(self.media_files(), [])

    def test_allowed_accounts_update(self):
        for user in self.allowed():
            with self.subTest(user=user):
                manifest = make_manifest()
                self.sign_in(user)
                response = self.update(manifest)

                self.assertEqual(response.status_code, 200)
                manifest.refresh_from_db()
                self.assertEqual(manifest.label, "New")

    def test_allowed_accounts_delete(self):
        for user in self.allowed():
            with self.subTest(user=user):
                manifest = make_manifest()
                self.sign_in(user)
                response = self.delete(manifest)

                self.assertEqual(response.status_code, 200)
                self.assertFalse(
                    models.IIIFManifest.objects.filter(pk=manifest.pk).exists()
                )


def jp2(size=(400, 300), **options):
    buffer = io.BytesIO()
    Image.new("RGB", size, (90, 40, 20)).save(buffer, format="JPEG2000", **options)
    return buffer.getvalue()


@override_settings(JP2_MIN_RESOLUTION_LEVELS=5, JP2_MAX_TILE_PIXELS=100_000)
class Jp2DepositTests(TestCase):
    """JPEG 2000 through the Image Service Manager POST (Cantaloupe is simulated)."""

    @classmethod
    def setUpTestData(cls):
        cls.editor = User.objects.create_user("jp2-editor", password="pw")
        cls.editor.groups.add(Group.objects.get(name="Resource Editor"))

    def setUp(self):
        pin_language(self)
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        media = override_settings(MEDIA_ROOT=self.media_root)
        media.enable()
        self.addCleanup(media.disable)
        for patcher in (
            mock.patch.object(
                CoreManifestManagerView,
                "fetch",
                return_value={"width": 400, "height": 300},
            ),
            mock.patch.object(jp2_profile, "LEVELS_CHECK_ABOVE_PIXELS", 10_000),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client.force_login(self.editor)

    def deposit(self, *files, url=URL, **data):
        uploads = [
            SimpleUploadedFile(name, content, content_type="application/octet-stream")
            for name, content in files
        ]
        return self.client.post(
            url,
            data={
                "operation": "create",
                "manifest_title": "Plate",
                "files": uploads,
                **data,
            },
        )

    def assert_nothing_written(self):
        self.assertFalse(models.IIIFManifest.objects.exists())
        self.assertFalse(models.File.objects.exists())
        self.assertEqual([f for _, _, f in os.walk(self.media_root) if f], [])

    def refusal(self, response):
        self.assertEqual(response.status_code, 400)
        return json.loads(response.content)["message"]

    def test_a_well_encoded_jp2_creates_a_manifest_served_by_its_file_name(self):
        good = jp2(tile_size=(256, 256), num_resolutions=6)

        response = self.deposit(("plate.jp2", good))

        self.assertEqual(response.status_code, 200)
        manifest = models.IIIFManifest.objects.get()
        canvas = manifest.manifest["sequences"][0]["canvases"][0]
        service = canvas["images"][0]["resource"]["service"]["@id"]
        self.assertTrue(service.endswith(".jp2"), service)
        self.assertEqual(models.File.objects.count(), 1)

    def test_an_uppercase_extension_is_accepted(self):
        good = jp2(tile_size=(256, 256), num_resolutions=6)

        self.assertEqual(self.deposit(("PLATE.JP2", good)).status_code, 200)

    def test_an_uppercase_extension_is_checked_too(self):
        self.assert_refused(("BAD.JP2", b"x" * 40))

    def assert_refused(self, *files):
        response = self.deposit(*files)
        message = self.refusal(response)
        self.assert_nothing_written()
        return message

    def test_a_jp2_of_one_resolution_level_is_refused_with_the_encoding_command(self):
        message = self.assert_refused(
            ("flat.jp2", jp2(tile_size=(256, 256), num_resolutions=1))
        )

        self.assertIn('"flat.jp2"', message)
        self.assertIn("1 resolution level, at least 5", message)
        self.assertIn(jp2_profile.RECOMMENDED_COMMAND, message)

    def test_a_large_untiled_jp2_is_refused(self):
        message = self.assert_refused(("wide.jp2", jp2((500, 400), num_resolutions=6)))

        self.assertIn("has tiles of 0.2 MP", message)

    def test_the_refusal_carries_a_translated_title_for_the_plugin_alert(self):
        response = self.deposit(("fake.jp2", b"hello" * 30))
        self.assertEqual(
            json.loads(response.content)["title"], "JPEG 2000 file refused"
        )
        response = self.deposit(
            ("fake.jp2", b"hello" * 30), url="/fr/image-service-manager"
        )
        self.assertEqual(
            json.loads(response.content)["title"], "Fichier JPEG 2000 refusé"
        )

    def test_the_upload_name_is_escaped_in_the_message(self):
        message = self.assert_refused(("<img src=x onerror=1>.jp2", b"nope" * 30))

        self.assertNotIn("<img", message)
        self.assertIn("&lt;img src=x onerror=1&gt;.jp2", message)

    def test_a_jp2_under_another_extension_is_refused(self):
        good = jp2(tile_size=(256, 256), num_resolutions=6)
        for name in ("plate.png", "plate.TIF", "plate.jpg"):
            with self.subTest(name):
                message = self.assert_refused((name, good))
                self.assertIn("is a JPEG 2000 file but is not named .jp2", message)

    def test_the_command_is_given_once_for_several_refused_files(self):
        message = self.assert_refused(
            ("a.jp2", jp2(tile_size=(256, 256), num_resolutions=1)),
            ("b.jp2", jp2(tile_size=(256, 256), num_resolutions=2)),
        )

        self.assertEqual(message.count(jp2_profile.RECOMMENDED_COMMAND), 1)

    def test_a_file_named_jp2_that_is_not_one_is_refused(self):
        for label, content in (("text", b"hello" * 30), ("png", PNG)):
            with self.subTest(label):
                message = self.assert_refused(("fake.jp2", content))
                self.assertIn("is not a valid JPEG 2000 file", message)

    def test_a_truncated_jp2_is_refused_not_a_500(self):
        good = jp2(tile_size=(256, 256), num_resolutions=6)

        message = self.assert_refused(("cut.jp2", good[:70]))

        self.assertIn("is not a valid JPEG 2000 file", message)

    def test_one_refused_file_refuses_the_whole_deposit(self):
        good = jp2(tile_size=(256, 256), num_resolutions=6)

        self.assert_refused(
            ("folio.png", PNG), ("good.jp2", good), ("bad.jp2", b"nope" * 20)
        )

    def test_the_refusal_is_in_the_language_of_the_url(self):
        response = self.deposit(
            ("fake.jp2", b"hello" * 30), url="/fr/image-service-manager"
        )

        self.assertIn("n'est pas un fichier JPEG 2000 valide", self.refusal(response))
        self.assert_nothing_written()

    def test_a_jp2_can_be_added_to_an_existing_manifest(self):
        manifest = make_manifest()
        good = jp2(tile_size=(256, 256), num_resolutions=6)

        response = self.client.post(
            URL,
            data={
                "manifest": manifest.url,
                "files": [SimpleUploadedFile("add.jp2", good)],
            },
        )

        self.assertEqual(response.status_code, 200)
        manifest.refresh_from_db()
        self.assertEqual(len(manifest.manifest["sequences"][0]["canvases"]), 1)

    def test_a_bad_jp2_is_refused_on_an_update_too(self):
        manifest = make_manifest()

        response = self.client.post(
            URL,
            data={
                "manifest": manifest.url,
                "files": [SimpleUploadedFile("bad.jp2", b"nope" * 30)],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(models.File.objects.exists())

    def test_the_other_types_are_served_as_before(self):
        response = self.deposit(("folio.png", PNG))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(models.File.objects.count(), 1)


class CorePostCanaryTests(SimpleTestCase):
    """Fails when an Arches upgrade changes ``post``: re-copy it into
    ``manuspectrum/views/manifest_manager.py`` and apply its two differences."""

    CORE_POST_SHA256 = (
        "53e32732330563f1a47b06216fd7ec332bb2c657f8735907c01f78a16d26b42d"
    )

    def test_the_copied_core_post_is_unchanged(self):
        source = inspect.getsource(CoreManifestManagerView.post)

        self.assertEqual(
            hashlib.sha256(source.encode()).hexdigest(), self.CORE_POST_SHA256
        )

    @staticmethod
    def without_project_lines(source):
        """The project ``post`` minus its marked differences: ``# ManuSpectrum:``
        comments, the ``".jp2",`` entry and every line from ``# ManuSpectrum: begin``
        to ``# ManuSpectrum: end``."""
        kept, skipping = [], False
        for line in textwrap.dedent(source).splitlines():
            stripped = line.strip()
            if stripped.startswith("# ManuSpectrum: begin"):
                skipping = True
            if not skipping and not (
                stripped.startswith("# ManuSpectrum:") or stripped == '".jp2",'
            ):
                kept.append(line)
            if stripped.startswith("# ManuSpectrum: end"):
                skipping = False
        return "\n".join(kept)

    def test_the_copy_is_the_core_post_without_its_marked_lines(self):
        project = inspect.getsource(ManifestManagerView.post)
        core = textwrap.dedent(inspect.getsource(CoreManifestManagerView.post))

        self.assertIn("# ManuSpectrum: begin", project)
        self.assertEqual(project.count("# ManuSpectrum: end"), 1)
        self.assertEqual(
            self.without_project_lines(project), "\n".join(core.splitlines())
        )

    def test_the_core_post_still_has_no_jp2_and_no_extension_point(self):
        source = inspect.getsource(CoreManifestManagerView.post)

        self.assertNotIn("jp2", source)
        self.assertIn("acceptable_types = [", source)


class CoreGuardCanaryTests(TestCase):
    """Fails once the installed Arches refuses these writes itself: then remove
    ``manuspectrum/views/manifest_manager.py``, its route and these tests."""

    def reaches_core_body(self, request):
        request.user = AnonymousUser()
        with self.assertRaises(models.IIIFManifest.DoesNotExist):
            CoreManifestManagerView.as_view()(request)

    def test_core_delete_has_no_group_check(self):
        self.reaches_core_body(
            RequestFactory().delete(
                URL,
                data=json.dumps({"manifest": "/manifest/unknown"}),
                content_type="application/json",
            )
        )

    def test_core_update_has_no_group_check(self):
        self.reaches_core_body(
            RequestFactory().post(
                URL, data={"manifest": "/manifest/unknown", "manifest_title": "x"}
            )
        )
