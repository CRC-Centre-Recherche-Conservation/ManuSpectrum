"""The Image Service Manager's write actions require Resource Editor or Resource Reviewer.

The project view answers Arches' ``manifest_manager`` route; its ``post`` and
``delete`` accept Resource Editor, Resource Reviewer and superusers only.

Usage:
    python manage.py test tests.test_manifest_manager_view --settings="tests.test_settings"
"""

import json
import os
import shutil
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

from arches.app.models import models
from arches.app.views.manifest_manager import (
    ManifestManagerView as CoreManifestManagerView,
)

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
