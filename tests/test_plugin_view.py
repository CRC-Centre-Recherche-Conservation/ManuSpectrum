"""What the project's plugin route adds to the Arches one: a 404 for a plugin
that does not exist, where the core view lets ``Plugin.DoesNotExist`` escape.

Usage:
    python manage.py test tests.test_plugin_view --settings="tests.test_settings"
"""

import uuid
from unittest import mock

from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import translation

from arches.app.models import models

from manuspectrum.views.plugin import PluginView

PLUGIN_ID = "6c2f3a3e-2f0a-4d7e-9a53-0c8c7f6f2b11"


def pin_language(test, language="en"):
    """Activate *language* for one test; a class decorator would hide the tests."""
    override = translation.override(language)
    override.__enter__()
    test.addCleanup(override.__exit__, None, None, None)


class PluginRoutingTests(SimpleTestCase):
    def setUp(self):
        pin_language(self)

    def test_a_slug_url_reaches_the_project_view(self):
        match = resolve("/en/plugins/init-workflow")

        self.assertIs(match.func.view_class, PluginView)
        self.assertEqual(match.url_name, "plugins")
        self.assertEqual(match.kwargs, {"slug": "init-workflow"})

    def test_the_french_urls_reach_it_too(self):
        with translation.override("fr"):
            by_slug = resolve("/fr/plugins/init-workflow")
            by_id = resolve(f"/fr/plugins/{PLUGIN_ID}")

        self.assertIs(by_slug.func.view_class, PluginView)
        self.assertEqual(by_slug.kwargs, {"slug": "init-workflow"})
        self.assertIs(by_id.func.view_class, PluginView)
        self.assertEqual(by_id.kwargs, {"pluginid": uuid.UUID(PLUGIN_ID)})

    def test_an_id_url_is_read_as_an_id_not_as_a_slug(self):
        match = resolve(f"/en/plugins/{PLUGIN_ID}")

        self.assertIs(match.func.view_class, PluginView)
        self.assertEqual(match.kwargs, {"pluginid": uuid.UUID(PLUGIN_ID)})

    def test_a_sub_path_reaches_the_project_view(self):
        match = resolve("/en/plugins/init-workflow/step/2")

        self.assertIs(match.func.view_class, PluginView)
        self.assertEqual(match.kwargs, {"slug": "init-workflow", "path": "step/2"})

    def test_reversal_still_builds_the_core_url(self):
        self.assertEqual(
            reverse("plugins", args=["init-workflow"]), "/en/plugins/init-workflow"
        )
        self.assertEqual(
            reverse("plugins", kwargs={"pluginid": PLUGIN_ID}),
            f"/en/plugins/{PLUGIN_ID}",
        )


class PluginViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.view = PluginView.as_view()

    def request(self, path="/en/plugins/init-workflow"):
        request = self.factory.get(path)
        request.user = mock.Mock(**{"has_perm.return_value": False})
        return request

    @mock.patch.object(
        models.Plugin.objects, "get", side_effect=models.Plugin.DoesNotExist
    )
    def test_an_unknown_slug_is_a_404(self, get):
        with self.assertRaises(Http404):
            self.view(self.request(), slug="ceci-nexiste-pas")

        get.assert_called_once_with(slug="ceci-nexiste-pas")

    @mock.patch.object(
        models.Plugin.objects, "get", side_effect=models.Plugin.DoesNotExist
    )
    def test_an_unknown_id_is_a_404(self, get):
        with self.assertRaises(Http404):
            self.view(self.request(), pluginid=uuid.UUID(PLUGIN_ID))

        get.assert_called_once_with(pk=uuid.UUID(PLUGIN_ID))

    @mock.patch.object(models.Plugin.objects, "get")
    def test_a_known_plugin_still_runs_the_core_view(self, get):
        get.return_value = mock.Mock()

        response = self.view(self.request(), slug="init-workflow")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/auth/?next="))

    @mock.patch.object(models.Plugin.objects, "get")
    def test_a_missing_object_of_another_model_is_not_a_404(self, get):
        get.return_value = mock.Mock()
        request = self.request()
        request.user.has_perm.side_effect = models.UserProfile.DoesNotExist

        with self.assertRaises(models.UserProfile.DoesNotExist):
            self.view(request, slug="init-workflow")


class UnknownPluginOverHttpTests(TestCase):
    def test_an_unknown_slug_answers_404(self):
        response = self.client.get("/en/plugins/ceci-nexiste-pas")

        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=False)
    def test_without_debug_the_404_is_the_site_page(self):
        response = self.client.get(f"/en/plugins/{PLUGIN_ID}")

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "errors/404.htm")
