"""Full-stack auth-barrier tests for the Biblissima connector and renderer config.

These tests go through ``django.test.Client`` — the full middleware +
URL-resolution + ``View.dispatch`` stack — unlike the other biblissima test
files, which call view methods directly (``view.get(req)``) and therefore
bypass the barrier on purpose.

CI-safe: no Arches package (graphs) is required. Positive-path assertions only
use request shapes that fail cheaply AFTER the auth check (400 validation
errors, the stats endpoint, and a short-circuited/mocked suggest proxy).

SECURITY INVARIANT under test: the DB user ``anonymous`` is *authenticated*
(Arches ``SetAnonymousUser`` middleware) and belongs to Guest + Resource
Exporter. Only a group check is a real barrier; ``EDITOR_GROUPS`` must never
contain those two groups.
"""

import json
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from manuspectrum.views import biblissima_proxy
from manuspectrum.views.permissions import EDITOR_GROUPS


class EditorGroupsConstantTests(TestCase):
    def test_excludes_anonymous_reachable_groups(self):
        self.assertNotIn("Resource Exporter", EDITOR_GROUPS)
        self.assertNotIn("Guest", EDITOR_GROUPS)

    def test_expected_members(self):
        self.assertEqual(
            EDITOR_GROUPS,
            (
                "Resource Editor",
                "Resource Reviewer",
                "RDM Administrator",
                "Application Administrator",
                "System Administrator",
                "Graph Editor",
            ),
        )

    def test_anonymous_user_is_in_no_editor_group(self):
        anonymous = User.objects.get(username="anonymous")
        self.assertFalse(
            anonymous.groups.filter(name__in=EDITOR_GROUPS).exists(),
            "The `anonymous` user must never belong to an editor group — "
            "that would open every gated endpoint to unauthenticated traffic.",
        )

    def test_renderer_config_uses_the_shared_constant(self):
        from manuspectrum.views import renderer_config

        self.assertIs(renderer_config.EDITOR_GROUPS, EDITOR_GROUPS)


class RendererConfigAuthTests(TestCase):
    """Regression tests for the renderer_config anonymous bypass.

    Before this fix the local tuple included "Resource Exporter" — the group
    the `anonymous` user belongs to — so anonymous POST/DELETE passed.
    """

    @classmethod
    def setUpTestData(cls):
        cls.anon_like = User.objects.create_user("anon_like", password="pw")
        cls.anon_like.groups.add(
            Group.objects.get(name="Guest"),
            Group.objects.get(name="Resource Exporter"),
        )
        cls.editor = User.objects.create_user("renderer_editor", password="pw")
        cls.editor.groups.add(Group.objects.get(name="Resource Editor"))

    def _post(self, body):
        # Plain path: SHOW_LANGUAGE_SWITCH is False (single-language LANGUAGES
        # in settings.py), so urlpatterns are NOT wrapped in i18n_patterns and
        # /renderer_config/ resolves unprefixed.
        return self.client.post(
            "/renderer_config/",
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_anonymous_post_is_forbidden(self):
        resp = self._post(
            {"rendererId": "9ec5c8f8-8a3f-4e6f-9dd8-7c1e5f5b0000", "name": "t"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_resource_exporter_member_is_forbidden(self):
        self.client.force_login(self.anon_like)
        resp = self._post(
            {"rendererId": "9ec5c8f8-8a3f-4e6f-9dd8-7c1e5f5b0000", "name": "t"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_editor_passes_the_barrier(self):
        self.client.force_login(self.editor)
        resp = self._post(
            {"rendererId": "9ec5c8f8-8a3f-4e6f-9dd8-7c1e5f5b0000", "name": "t"}
        )
        self.assertEqual(resp.status_code, 200)


class BiblissimaAuthBarrierTests(TestCase):
    """Anonymous and non-editor requests must get a JSON 403 on all 12 routes."""

    # (http method, url name, reverse kwargs, POST body)
    ROUTES = [
        ("get", "biblissima-suggest", None, None),
        ("get", "biblissima-entity", {"qid": "Q1"}, None),
        ("get", "biblissima-search", None, None),
        ("get", "biblissima-search-manuscripts", None, None),
        ("post", "biblissima-check-duplicates", None, "{}"),
        ("get", "biblissima-manuscript-illuminations", None, None),
        ("get", "biblissima-illumination-detail", {"ifdata_hash": "deadbeef"}, None),
        ("post", "biblissima-create-resource", None, "{}"),
        ("post", "biblissima-create-all", None, "{}"),
        ("post", "biblissima-add-alt-name", None, "{}"),
        ("get", "biblissima-stats", None, None),
        ("post", "biblissima-link-to-project", None, "{}"),
    ]

    @classmethod
    def setUpTestData(cls):
        cls.outsider = User.objects.create_user("outsider", password="pw")
        cls.outsider.groups.add(
            Group.objects.get(name="Guest"),
            Group.objects.get(name="Resource Exporter"),
        )

    def setUp(self):
        # Belt-and-braces: even while the barrier is missing (red phase) or
        # broken (regression), no test may reach the network.
        patcher = mock.patch.object(biblissima_proxy, "_bib_request")
        self.mock_bib = patcher.start()
        self.mock_bib.return_value.json.return_value = {
            "search": [],
            "query": {"search": []},
            "entities": {},
        }
        self.addCleanup(patcher.stop)
        cache.clear()  # cache_page state must not leak between tests

    def _call(self, method, name, kwargs, body):
        url = reverse(name, kwargs=kwargs)
        if method == "get":
            return self.client.get(url)
        return self.client.post(url, data=body, content_type="application/json")

    def test_anonymous_gets_json_403_on_every_route(self):
        for method, name, kwargs, body in self.ROUTES:
            with self.subTest(route=name):
                resp = self._call(method, name, kwargs, body)
                self.assertEqual(resp.status_code, 403)
                self.assertIn("application/json", resp["Content-Type"])
                self.assertFalse(resp.json().get("success", True))

    def test_guest_and_exporter_member_gets_403(self):
        self.client.force_login(self.outsider)
        for method, name, kwargs, body in [
            ("get", "biblissima-suggest", None, None),
            ("post", "biblissima-create-resource", None, "{}"),
        ]:
            with self.subTest(route=name):
                resp = self._call(method, name, kwargs, body)
                self.assertEqual(resp.status_code, 403)

    def test_routes_list_covers_every_biblissima_route(self):
        # Drift guard: if a new api/biblissima/* route ships, it must be added
        # to ROUTES above so the anonymous-403 sweep covers it.
        from manuspectrum import urls as project_urls

        registered = {
            pattern.name
            for pattern in project_urls.urlpatterns
            if getattr(pattern, "name", None) and pattern.name.startswith("biblissima-")
        }
        covered = {name for _method, name, _kwargs, _body in self.ROUTES}
        self.assertEqual(registered, covered)


class BiblissimaAuthPassThroughTests(TestCase):
    """Editors must sail through the barrier and hit normal view logic.

    Every request here is chosen to fail cheaply AFTER auth (400 validation,
    stats) — no network, no Arches graphs needed.
    """

    @classmethod
    def setUpTestData(cls):
        cls.editor = User.objects.create_user("editor", password="pw")
        cls.editor.groups.add(Group.objects.get(name="Resource Editor"))
        cls.staff_editor = User.objects.create_user(
            "staff_editor", password="pw", is_staff=True
        )
        cls.staff_editor.groups.add(Group.objects.get(name="Resource Editor"))

    def setUp(self):
        cache.clear()

    def test_editor_reaches_link_to_project_validation(self):
        self.client.force_login(self.editor)
        resp = self.client.post(
            reverse("biblissima-link-to-project"),
            data="not json",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)  # auth passed, body rejected

    def test_editor_reaches_create_all_validation_via_inherited_dispatch(self):
        # BiblissimaCreateAllView is NOT decorated itself: it inherits the
        # decorated dispatch from BiblissimaCreateResourceView. This test
        # locks that inheritance (and the anonymous test locks the 403 side).
        self.client.force_login(self.editor)
        resp = self.client.post(
            reverse("biblissima-create-all"),
            data=json.dumps({"resourceType": "Nope", "items": [{}]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)  # unsupported resourceType

    def test_editor_without_staff_still_blocked_on_stats(self):
        self.client.force_login(self.editor)
        resp = self.client.get(reverse("biblissima-stats"))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json(), {"error": "Forbidden"})

    def test_staff_editor_gets_stats(self):
        self.client.force_login(self.staff_editor)
        resp = self.client.get(reverse("biblissima-stats"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("semaphore_capacity", resp.json())


class BiblissimaCachePrivacyTests(TestCase):
    """The cached GET proxies must be private-to-authenticated yet still
    benefit from Django's server-side page cache."""

    @classmethod
    def setUpTestData(cls):
        cls.editor = User.objects.create_user("cache_editor", password="pw")
        cls.editor.groups.add(Group.objects.get(name="Resource Editor"))

    def setUp(self):
        cache.clear()

    def test_suggest_is_private_and_auth_precedes_cache(self):
        self.client.force_login(self.editor)
        # q shorter than 2 chars short-circuits before any upstream call
        url = reverse("biblissima-suggest") + "?q=a"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("private", resp["Cache-Control"])
        # The response is now in the page cache; an anonymous request for the
        # SAME URL must still be rejected (dispatch check precedes the cached get)
        self.client.logout()
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_private_header_does_not_disable_server_side_cache(self):
        with mock.patch.object(biblissima_proxy, "_bib_request") as bib:
            bib.return_value.json.return_value = {
                "search": [],
                "query": {"search": []},
                "entities": {},
            }
            self.client.force_login(self.editor)
            url = reverse("biblissima-suggest") + "?q=cache-probe"
            r1 = self.client.get(url)
            self.assertEqual(r1.status_code, 200)
            upstream_calls = bib.call_count
            self.assertGreater(upstream_calls, 0)  # first hit went upstream
            r2 = self.client.get(url)
            self.assertEqual(r2.status_code, 200)
            # Second hit must be served from the page cache: if private had
            # been patched INSIDE cache_page, UpdateCacheMiddleware would
            # refuse to store and this count would grow.
            self.assertEqual(bib.call_count, upstream_calls)
            self.assertIn("private", r2["Cache-Control"])
