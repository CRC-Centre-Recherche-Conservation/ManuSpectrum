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

from django.contrib.auth.models import Group, User
from django.test import TestCase

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
