"""What the project's templates route adds to the Arches one.

A Knockout component template under a shared prefix is rendered once per
language and template stamp, then served from the cache with an ETag and a
public lifetime; every other name reaches the core view uncached; a name no
loader finds is a bodyless 404.

Usage:
    python manage.py test tests.test_knockout_templates --settings="tests.test_settings"
"""

import copy
import os
import re
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import HttpResponse
from django.template import TemplateDoesNotExist, engines
from django.template.utils import get_app_template_dirs
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve
from django.utils import translation

from manuspectrum.views import knockout_templates
from manuspectrum.views.knockout_templates import (
    SHARED_PREFIXES,
    STAMPED_DISTRIBUTIONS,
    is_shared,
    knockout_template,
    template_stamp,
)

MODULE = "manuspectrum.views.knockout_templates"
SWITCHER = "views/components/language-switcher.htm"

# Context values that differ from one reader to the next, as Django tags see them.
PER_READER = re.compile(
    r"\b(csrf_token|user|request|perms|messages|map_info|session|debug|sql_queries)\b"
)
DJANGO_TAG = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
STRING_LITERAL = re.compile(r"\"[^\"]*\"|'[^']*'")
INCLUDED = re.compile(r"\{%\s*(?:include|extends)\s+[\"']([^\"']+)[\"']")
INCLUDE_ARGUMENT = re.compile(
    r"\{%\s*(?:include|extends)\s+((?:\"[^\"]*\"|'[^']*'|[^\s%])+)"
)
LOADED = re.compile(r"\{%\s*load\s+(.*?)\s*%\}", re.S)
# What a shared template may load: whole libraries, or ``library:tag`` for a
# library allowed one tag at a time (webpack_loader's render_bundle and
# get_files read the request).
SHARED_LIBRARIES = {"i18n", "static", "template_tags", "webpack_loader:webpack_static"}


def loaded_libraries(arguments):
    """What a ``{% load %}`` pulls in: each library, or ``library:tag`` per tag
    of the ``{% load tag … from library %}`` form."""
    bits = arguments.split()
    if len(bits) >= 3 and bits[-2] == "from":
        return [f"{bits[-1]}:{tag}" for tag in bits[:-2]]
    return bits


def is_allowed_load(library):
    return library in SHARED_LIBRARIES or library.split(":")[0] in SHARED_LIBRARIES


def pin_language(test, language="en"):
    """Activate *language* for one test; a class decorator would hide the tests."""
    override = translation.override(language)
    override.__enter__()
    test.addCleanup(override.__exit__, None, None, None)


class TemplateRoutingTests(SimpleTestCase):
    def setUp(self):
        pin_language(self)

    def test_a_template_url_reaches_the_project_view(self):
        match = resolve(f"/en/templates/{SWITCHER}")

        self.assertIs(match.func, knockout_template)
        self.assertEqual(match.url_name, "templates")
        self.assertEqual(match.kwargs, {"template": SWITCHER})

    def test_the_french_url_reaches_it_too(self):
        with translation.override("fr"):
            match = resolve(f"/fr/templates/{SWITCHER}")

        self.assertIs(match.func, knockout_template)


class SharedNameTests(SimpleTestCase):
    def test_names_the_browser_loader_asks_for_are_shared(self):
        for name in (
            SWITCHER,
            "views/components/widgets/text.htm",
            "views/report-templates/tabbed.htm",
            "views/resource/permissions/permissions-manager.htm",
            "views/resource/related-resources/related-resources-manager.htm",
        ):
            with self.subTest(name=name):
                self.assertTrue(is_shared(name))

    def test_other_or_non_canonical_names_are_not(self):
        for name in (
            "",
            "login.htm",
            "javascript.htm",
            "views/resource/editor.htm",
            "views/components/../../javascript.htm",
            "views/components/./widgets/text.htm",
            "views/components//widgets/text.htm",
            "views/components/widgets/text",
            "/views/components/widgets/text.htm",
            "views/componentsX/text.htm",
        ):
            with self.subTest(name=name):
                self.assertFalse(is_shared(name))


class SharedSubtreeTests(SimpleTestCase):
    """The shared subtrees, in every template directory, print nothing per reader."""

    def shared_files(self):
        engine = engines["django"].engine
        for root in (*engine.dirs, *get_app_template_dirs("templates")):
            for prefix in SHARED_PREFIXES:
                folder = Path(root, prefix)
                if folder.is_dir():
                    yield from (path for path in folder.rglob("*") if path.is_file())

    def test_the_shared_subtrees_are_found(self):
        self.assertGreater(len(list(self.shared_files())), 100)

    def test_no_shared_template_reads_a_per_reader_value(self):
        offenders = [
            f"{path}: {tag}"
            for path in self.shared_files()
            for tag in DJANGO_TAG.findall(path.read_text(errors="replace"))
            if PER_READER.search(STRING_LITERAL.sub("", tag))
        ]

        self.assertEqual(offenders, [])

    def test_shared_templates_only_include_shared_templates(self):
        outside = [
            f"{path}: {name}"
            for path in self.shared_files()
            for name in INCLUDED.findall(path.read_text(errors="replace"))
            if not is_shared(name)
        ]

        self.assertEqual(outside, [])

    def test_shared_templates_load_only_libraries_that_read_no_request(self):
        offenders = [
            f"{path}: {library}"
            for path in self.shared_files()
            for arguments in LOADED.findall(path.read_text(errors="replace"))
            for library in loaded_libraries(arguments)
            if not is_allowed_load(library)
        ]

        self.assertEqual(offenders, [])

    def test_the_load_guard_admits_webpack_static_alone_from_webpack_loader(self):
        for arguments, allowed in (
            ("i18n", True),
            ("trans from i18n", True),
            ("webpack_static from webpack_loader", True),
            ("webpack_loader", False),
            ("render_bundle from webpack_loader", False),
            ("webpack_static get_files from webpack_loader", False),
            ("i18n webpack_loader", False),
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual(
                    all(map(is_allowed_load, loaded_libraries(arguments))), allowed
                )

    def test_shared_templates_include_and_extend_string_literals_only(self):
        offenders = [
            f"{path}: {argument}"
            for path in self.shared_files()
            for argument in INCLUDE_ARGUMENT.findall(path.read_text(errors="replace"))
            if not STRING_LITERAL.fullmatch(argument)
        ]

        self.assertEqual(offenders, [])


class TemplateStampTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "templates" / "views").mkdir(parents=True)
        (self.root / "locale" / "fr" / "LC_MESSAGES").mkdir(parents=True)
        self.template = self.root / "templates" / "views" / "a.htm"
        self.template.write_text("a")
        self.catalog = self.root / "locale" / "fr" / "LC_MESSAGES" / "django.mo"
        self.catalog.write_bytes(b"mo")
        for cached in (
            knockout_templates._process_stamp,
            knockout_templates._distribution_versions,
        ):
            cached.cache_clear()
            self.addCleanup(cached.cache_clear)

    def stamp(self, debug=True):
        with override_settings(DEBUG=debug, APP_ROOT=str(self.root)):
            return template_stamp()

    def test_the_stamp_holds_while_nothing_changes(self):
        self.assertRegex(self.stamp(), r"^[0-9a-f]{12}$")
        self.assertEqual(self.stamp(), self.stamp())

    def test_an_edited_template_changes_the_stamp(self):
        before = self.stamp()
        self.template.write_text("ab")

        self.assertNotEqual(self.stamp(), before)

    def test_a_recompiled_catalogue_changes_the_stamp(self):
        before = self.stamp()
        os.utime(self.catalog, ns=(1, 1))

        self.assertNotEqual(self.stamp(), before)

    def test_an_upgraded_distribution_changes_the_stamp(self):
        before = self.stamp()
        knockout_templates._distribution_versions.cache_clear()

        with mock.patch(f"{MODULE}.metadata.version", return_value="99.0.0"):
            self.assertNotEqual(self.stamp(), before)

    def test_under_debug_the_versions_are_still_read_once(self):
        with mock.patch(f"{MODULE}.metadata.version", return_value="1.0") as version:
            self.stamp()
            self.stamp()

        self.assertEqual(version.call_count, len(STAMPED_DISTRIBUTIONS))

    def test_a_file_that_vanishes_during_the_walk_is_left_out(self):
        real_stat = os.stat
        vanished = str(self.template)

        def stat(path, *args, **kwargs):
            if os.fspath(path) == vanished:
                raise FileNotFoundError(path)
            return real_stat(path, *args, **kwargs)

        with mock.patch(f"{MODULE}.os.stat", side_effect=stat):
            during = self.stamp()
        self.template.unlink()

        self.assertEqual(self.stamp(), during)

    def test_without_debug_the_stamp_is_read_once_per_process(self):
        before = self.stamp(debug=False)
        self.template.write_text("ab")

        self.assertEqual(self.stamp(debug=False), before)


class FakeTemplate:
    """A loaded template that counts its renders and may read the CSRF token."""

    def __init__(self, text):
        self.text = text
        self.reads_csrf = False
        self.renders = 0

    def render(self, context=None, request=None):
        self.renders += 1
        if self.reads_csrf:
            request.META["CSRF_COOKIE_NEEDS_UPDATE"] = True
        return self.text


@override_settings(KNOCKOUT_TEMPLATE_MAX_AGE=600, KNOCKOUT_TEMPLATE_CACHE_TTL=3600)
class KnockoutTemplateViewTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        pin_language(self)
        self.factory = RequestFactory()
        self.template = FakeTemplate("<div>switcher</div>")
        self.get_template = self.patch("get_template", return_value=self.template)
        self.stamp = self.patch("template_stamp", return_value="stamp-1")
        self.core = self.patch("main.templates", return_value=HttpResponse("core"))

    def patch(self, target, **kwargs):
        patcher = mock.patch(f"{MODULE}.{target}", **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def get(self, name, **headers):
        return knockout_template(
            self.factory.get(f"/en/templates/{name}", **headers), name
        )

    def test_a_shared_template_is_served_with_an_etag_and_a_public_lifetime(self):
        response = self.get(SWITCHER)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"<div>switcher</div>")
        self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")
        self.assertRegex(response.headers["ETag"], r'^"[0-9a-f]{32}"$')
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=600")
        self.core.assert_not_called()

    def test_a_second_request_is_served_from_the_cache(self):
        self.get(SWITCHER)
        response = self.get(SWITCHER)

        self.assertEqual(response.content, b"<div>switcher</div>")
        self.assertEqual(self.template.renders, 1)

    def test_a_client_holding_the_etag_gets_a_304_with_the_same_headers(self):
        etag = self.get(SWITCHER).headers["ETag"]

        response = self.get(SWITCHER, HTTP_IF_NONE_MATCH=etag)

        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.headers["ETag"], etag)
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=600")

    def test_the_weak_form_of_the_etag_is_honoured(self):
        etag = self.get(SWITCHER).headers["ETag"]

        response = self.get(SWITCHER, HTTP_IF_NONE_MATCH=f"W/{etag}")

        self.assertEqual(response.status_code, 304)

    def test_each_language_has_its_own_entry(self):
        self.get(SWITCHER)
        self.template.text = "<div>sélecteur</div>"

        with translation.override("fr"):
            response = self.get(SWITCHER)

        self.assertEqual(response.content.decode(), "<div>sélecteur</div>")
        self.assertEqual(self.template.renders, 2)

    def test_a_new_stamp_renders_again(self):
        self.get(SWITCHER)
        self.stamp.return_value = "stamp-2"

        self.get(SWITCHER)

        self.assertEqual(self.template.renders, 2)

    def test_an_unknown_shared_name_is_a_bodyless_404_and_is_not_kept(self):
        self.get_template.side_effect = TemplateDoesNotExist("nope")

        response = self.get("views/components/nope.htm")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        self.get_template.side_effect = None
        self.assertEqual(self.get("views/components/nope.htm").status_code, 200)

    def test_a_render_that_reads_the_csrf_token_is_neither_shared_nor_kept(self):
        self.template.reads_csrf = True

        with self.assertLogs(MODULE, "WARNING"):
            response = self.get(SWITCHER)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertNotIn("ETag", response.headers)
        self.template.reads_csrf = False
        self.get(SWITCHER)
        self.assertEqual(self.template.renders, 2)

    def test_a_render_while_the_middleware_renews_the_csrf_cookie_is_not_kept(self):
        with self.assertNoLogs(MODULE, "WARNING"):
            response = self.get(SWITCHER, CSRF_COOKIE_NEEDS_UPDATE=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"<div>switcher</div>")
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.get(SWITCHER)
        self.assertEqual(self.template.renders, 2)

    def test_a_kept_template_is_private_while_the_middleware_renews_the_cookie(self):
        self.get(SWITCHER)

        response = self.get(SWITCHER, CSRF_COOKIE_NEEDS_UPDATE=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"<div>switcher</div>")
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertEqual(self.template.renders, 1)

    def test_other_names_reach_the_core_view_uncached(self):
        for name in ("login.htm", "views/components/../../javascript.htm"):
            with self.subTest(name=name):
                response = self.get(name)

                self.assertEqual(response.content, b"core")
                self.assertNotIn("Cache-Control", response.headers)
        self.assertEqual(self.core.call_count, 2)
        self.assertEqual(self.template.renders, 0)

    def test_an_unknown_name_outside_the_shared_subtrees_is_a_404(self):
        self.get_template.side_effect = TemplateDoesNotExist("nope.htm")

        response = self.get("nope.htm")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        self.core.assert_not_called()

    def test_a_directory_name_is_a_404(self):
        self.get_template.side_effect = IsADirectoryError("views/components/")

        self.assertEqual(self.get("views/components/").status_code, 404)
        self.core.assert_not_called()

    def test_a_shared_name_through_a_file_is_a_bodyless_404_and_is_not_kept(self):
        name = "views/components/widgets/text.htm/a.htm"
        self.get_template.side_effect = NotADirectoryError(name)

        response = self.get(name)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        self.get_template.side_effect = None
        self.assertEqual(self.get(name).status_code, 200)
        self.assertEqual(self.template.renders, 1)

    def test_a_name_with_a_nul_byte_is_a_404_without_loading(self):
        for name in ("a\x00.htm", "views/components/a\x00.htm"):
            with self.subTest(name=name):
                request = self.factory.get("/en/templates/", {"template": name})

                response = knockout_template(request, "")

                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.content, b"")
        self.get_template.assert_not_called()
        self.core.assert_not_called()

    def test_a_template_that_is_not_utf8_is_a_fault(self):
        for name in (SWITCHER, "login.htm"):
            with self.subTest(name=name):
                self.get_template.side_effect = UnicodeDecodeError(
                    "utf-8", b"\xff", 0, 1, "invalid start byte"
                )

                with self.assertRaises(UnicodeDecodeError):
                    self.get(name)

    def test_a_write_reaches_the_core_view(self):
        request = self.factory.post(f"/en/templates/{SWITCHER}")

        self.assertEqual(knockout_template(request, SWITCHER).content, b"core")

    def test_the_query_string_name_is_served_like_the_path(self):
        request = self.factory.get("/en/templates/", {"template": SWITCHER})

        response = knockout_template(request, "")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=600")
        self.core.assert_not_called()

    def test_an_empty_name_is_a_404(self):
        response = knockout_template(self.factory.get("/en/templates/"), "")

        self.assertEqual(response.status_code, 404)
        self.core.assert_not_called()


@override_settings(KNOCKOUT_TEMPLATE_MAX_AGE=600)
class RenderedTemplateTests(TestCase):
    """Real templates through the real context processors."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        pin_language(self)
        self.factory = RequestFactory()

    def get(self, name=SWITCHER):
        request = self.factory.get(f"/en/templates/{name}")
        request.user = AnonymousUser()
        return knockout_template(request, name)

    def test_the_language_switcher_renders_with_its_language_url(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/en/i18n/setlang/", response.content)

    def test_a_kept_template_costs_no_query(self):
        self.get()

        with self.assertNumQueries(0):
            response = self.get()

        self.assertEqual(response.status_code, 200)

    def test_english_and_french_are_rendered_apart(self):
        english = self.get().content
        with translation.override("fr"):
            french = self.get().content

        self.assertNotEqual(english, french)
        self.assertIn(b"/fr/i18n/setlang/", french)

    def test_a_missing_shared_template_is_a_404(self):
        self.assertEqual(
            self.get("views/components/does-not-exist.htm").status_code, 404
        )

    def test_a_shared_name_through_a_file_is_a_bodyless_404(self):
        response = self.get("views/components/widgets/text.htm/a.htm")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")

    def test_a_name_through_a_page_template_is_a_404(self):
        self.assertEqual(self.get("login.htm/x").status_code, 404)

    def test_a_shared_name_with_a_nul_byte_is_a_404(self):
        request = self.factory.get(
            "/en/templates/", {"template": "views/components/a\x00.htm"}
        )
        request.user = AnonymousUser()

        self.assertEqual(knockout_template(request, "").status_code, 404)

    def test_a_real_template_reading_the_csrf_token_is_private_and_not_kept(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        name = "views/components/csrf-probe.htm"
        (folder / name).parent.mkdir(parents=True)
        (folder / name).write_text("<form>{% csrf_token %}</form>")
        templates = copy.deepcopy(settings.TEMPLATES)
        templates[0]["DIRS"] = [str(folder), *templates[0].get("DIRS", [])]

        with override_settings(TEMPLATES=templates):
            with self.assertLogs(MODULE, "WARNING"):
                first = self.get(name)
            with self.assertLogs(MODULE, "WARNING"):
                second = self.get(name)

        for response in (first, second):
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"csrfmiddlewaretoken", response.content)
            self.assertEqual(response.headers["Cache-Control"], "private, no-store")
            self.assertNotIn("ETag", response.headers)

    def test_through_the_middleware_the_client_can_revalidate(self):
        first = self.client.get(f"/en/templates/{SWITCHER}")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["Cache-Control"], "public, max-age=600")
        second = self.client.get(
            f"/en/templates/{SWITCHER}", HTTP_IF_NONE_MATCH=first.headers["ETag"]
        )
        self.assertEqual(second.status_code, 304)

    def test_through_the_middleware_a_malformed_csrf_cookie_gets_a_private_answer(
        self,
    ):
        self.client.get(f"/en/templates/{SWITCHER}")
        self.client.cookies["csrftoken"] = "!!"

        response = self.client.get(f"/en/templates/{SWITCHER}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertIn("csrftoken", response.cookies)
