"""The renderer-configuration API, read and write, without a database.

``tests/test_renderer_config_guard.py`` locks the in-use lookup and how a POST
body splits into columns and ``config``. This file covers the rest of the two
views: what each read returns, and the two protections a write has to survive —
a seeded preset is editable by a superuser only, and deletable by nobody, while
an ordinary configuration is deletable only once no file still points at it.

Everything the views touch is patched, so these run under ``SimpleTestCase``:
the barrier being asserted is the code path, not the state of a fixture.
"""

import json
from unittest import mock

from django.test import RequestFactory, SimpleTestCase
from django.utils import translation

from manuspectrum.constants.xy_presets import XY_PRESETS
from manuspectrum.views.renderer_config import (
    RendererConfigView,
    RendererView,
    configuration_is_in_use,
)

RENDERER_ID = "e93b7b27-40d8-4141-996e-e59ff08742f3"
SEEDED_CONFIG = XY_PRESETS["fors"]["config_id"]
CURATOR_CONFIG = "d5f0e1a2-3b4c-4d5e-8f90-1a2b3c4d5e6f"
MEASUREMENT_NODE = "8fe5161a-7bf2-11ef-b1e5-dd514ecd97bc"


def body_of(response):
    return json.loads(response.content)


class EnglishResponseTestCase(SimpleTestCase):
    """The not-found bodies are translated, so the language has to be pinned.

    ``LocaleMiddleware`` activates a language and never undoes it, so any
    earlier test that fetched a ``/fr/`` URL leaves French active for this one.
    """

    def setUp(self):
        override = translation.override("en")
        override.__enter__()
        self.addCleanup(override.__exit__, None, None, None)


class RendererViewTests(EnglishResponseTestCase):
    def setUp(self):
        super().setUp()
        self.request = RequestFactory().get("/renderer/")
        patched = mock.patch("manuspectrum.views.renderer_config.RendererConfig")
        self.model = patched.start()
        self.addCleanup(patched.stop)

    def test_no_renderer_id_returns_an_empty_list(self):
        response = RendererView().get(self.request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body_of(response), [])
        self.model.objects.filter.assert_not_called()

    def test_an_unknown_renderer_is_a_404(self):
        self.model.objects.filter.return_value.__bool__.return_value = False

        response = RendererView().get(self.request, renderer_id=RENDERER_ID)

        self.assertEqual(response.status_code, 404)
        self.assertIn(b"Renderers do not exist", response.content)

    def test_each_configuration_carries_whether_it_is_protected(self):
        queryset = self.model.objects.filter.return_value
        queryset.__bool__.return_value = True
        queryset.values.return_value = [
            {"configid": SEEDED_CONFIG, "name": "FORS"},
            {"configid": CURATOR_CONFIG, "name": "My own"},
        ]

        response = RendererView().get(self.request, renderer_id=RENDERER_ID)

        self.assertEqual(
            body_of(response),
            {
                "configs": [
                    {"configid": SEEDED_CONFIG, "name": "FORS", "protected": True},
                    {"configid": CURATOR_CONFIG, "name": "My own", "protected": False},
                ]
            },
        )

    def test_it_asks_only_for_the_renderer_it_was_given(self):
        queryset = self.model.objects.filter.return_value
        queryset.__bool__.return_value = True
        queryset.values.return_value = []

        RendererView().get(self.request, renderer_id=RENDERER_ID)

        self.model.objects.filter.assert_called_once_with(rendererid=RENDERER_ID)


class RendererConfigReadTests(EnglishResponseTestCase):
    def setUp(self):
        super().setUp()
        self.request = RequestFactory().get("/renderer_config/")
        patched = mock.patch("manuspectrum.views.renderer_config.RendererConfig")
        self.model = patched.start()
        self.addCleanup(patched.stop)

    def test_no_id_returns_every_configuration(self):
        rows = [{"configid": SEEDED_CONFIG}, {"configid": CURATOR_CONFIG}]
        self.model.objects.all.return_value.values.return_value = rows

        response = RendererConfigView().get(self.request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body_of(response), rows)

    def test_a_known_id_returns_that_configuration(self):
        queryset = self.model.objects.filter.return_value
        queryset.__bool__.return_value = True
        queryset.values.return_value = [{"configid": CURATOR_CONFIG, "name": "My own"}]

        response = RendererConfigView().get(
            self.request, renderer_config_id=CURATOR_CONFIG
        )

        self.assertEqual(
            body_of(response), [{"configid": CURATOR_CONFIG, "name": "My own"}]
        )
        self.model.objects.filter.assert_called_once_with(configid=CURATOR_CONFIG)

    def test_an_unknown_id_is_a_404(self):
        self.model.objects.filter.return_value.__bool__.return_value = False

        response = RendererConfigView().get(
            self.request, renderer_config_id=CURATOR_CONFIG
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn(b"Renderers config does not exist", response.content)


class ConfigurationInUseTests(SimpleTestCase):
    def _models(self, file_nodes, exists=False):
        patched = mock.patch("manuspectrum.views.renderer_config.models")
        models = patched.start()
        self.addCleanup(patched.stop)
        node_lookup = models.Node.objects.filter.return_value
        node_lookup.values_list.return_value.distinct.return_value = file_nodes
        models.TileModel.objects.filter.return_value.exists.return_value = exists
        return models

    def test_a_graph_with_no_file_node_reports_nothing_in_use(self):
        models = self._models([])

        self.assertFalse(configuration_is_in_use(CURATOR_CONFIG))
        # An empty Q matches every tile, so the short-circuit is the whole
        # protection: reaching the query would report everything as in use.
        models.TileModel.objects.filter.assert_not_called()

    def test_it_only_considers_file_list_nodes(self):
        models = self._models([(MEASUREMENT_NODE, MEASUREMENT_NODE)])

        configuration_is_in_use(CURATOR_CONFIG)

        models.Node.objects.filter.assert_called_once_with(datatype="file-list")

    def test_a_matching_tile_puts_the_configuration_in_use(self):
        models = self._models([(MEASUREMENT_NODE, MEASUREMENT_NODE)], exists=True)

        self.assertTrue(configuration_is_in_use(CURATOR_CONFIG))

        query = models.TileModel.objects.filter.call_args.args[0]
        self.assertIn(f"data__{MEASUREMENT_NODE}__contains", str(query))
        self.assertIn(CURATOR_CONFIG, str(query))

    def test_no_matching_tile_leaves_the_configuration_free(self):
        self._models([(MEASUREMENT_NODE, MEASUREMENT_NODE)], exists=False)

        self.assertFalse(configuration_is_in_use(CURATOR_CONFIG))


class WriteTestCase(SimpleTestCase):
    """Both write methods sit behind the editor-group barrier.

    ``tests/test_biblissima_auth.py`` locks that barrier full-stack; here it is
    satisfied so the branch under test is the one being read.
    """

    def setUp(self):
        self._patch(
            "arches.app.utils.decorators.permission_group_required", return_value=True
        )
        self.model = self._patch("manuspectrum.views.renderer_config.RendererConfig")
        self.serializer = self._patch(
            "manuspectrum.views.renderer_config.JSONSerializer"
        )
        self.serializer.return_value.serialize.return_value = "serialized-row"

    def _patch(self, target, **kwargs):
        patched = mock.patch(target, **kwargs)
        self.addCleanup(patched.stop)
        return patched.start()

    def _request(self, method, body=None, is_superuser=False):
        factory = RequestFactory()
        if method == "post":
            request = factory.post(
                "/renderer_config/",
                data=json.dumps(body),
                content_type="application/json",
            )
        else:
            request = factory.delete("/renderer_config/")
        request.user = mock.Mock(is_superuser=is_superuser)
        return request


class RendererConfigSaveTests(WriteTestCase):
    def test_a_curator_cannot_edit_a_seeded_preset(self):
        request = self._request(
            "post",
            {"rendererId": RENDERER_ID, "name": "FORS", "delimiterCharacter": ","},
        )

        response = RendererConfigView().post(request, renderer_config_id=SEEDED_CONFIG)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(body_of(response)["saved"], False)
        self.assertEqual(body_of(response)["reason"], "protected")
        self.assertIn("Duplicate it", body_of(response)["message"])
        self.model.objects.get.assert_not_called()

    def test_a_superuser_may_edit_a_seeded_preset(self):
        stored = self.model.objects.get.return_value
        stored.config = {"presetKey": "fors", "delimiterCharacter": ";"}
        request = self._request(
            "post",
            {
                "rendererId": RENDERER_ID,
                "name": "FORS",
                "description": "reflectance",
                "delimiterCharacter": ",",
            },
            is_superuser=True,
        )

        response = RendererConfigView().post(request, renderer_config_id=SEEDED_CONFIG)

        self.assertEqual(response.status_code, 200)
        self.model.objects.get.assert_called_once_with(configid=SEEDED_CONFIG)
        self.assertEqual(stored.name, "FORS")
        self.assertEqual(stored.description, "reflectance")
        # presetKey is not a field the panel owns, so the edit carries it over.
        self.assertEqual(
            stored.config, {"delimiterCharacter": ",", "presetKey": "fors"}
        )
        stored.save.assert_called_once_with()


class RendererConfigDeleteTests(WriteTestCase):
    def _delete(self, renderer_config_id, in_use=False, is_superuser=False):
        with mock.patch(
            "manuspectrum.views.renderer_config.configuration_is_in_use",
            return_value=in_use,
        ) as in_use_check:
            response = RendererConfigView().delete(
                self._request("delete", is_superuser=is_superuser),
                renderer_config_id=renderer_config_id,
            )
        return response, in_use_check

    def test_a_seeded_preset_is_refused_even_to_a_superuser(self):
        response, in_use_check = self._delete(SEEDED_CONFIG, is_superuser=True)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(body_of(response)["deleted"], False)
        self.assertEqual(body_of(response)["reason"], "protected")
        self.assertIn("cannot be deleted", body_of(response)["message"])
        self.model.objects.get.assert_not_called()
        in_use_check.assert_not_called()

    def test_a_configuration_a_file_still_points_at_is_kept(self):
        response, _ = self._delete(CURATOR_CONFIG, in_use=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body_of(response), {"deleted": False})
        self.model.objects.get.return_value.delete.assert_not_called()

    def test_an_unreferenced_configuration_is_deleted(self):
        stored = self.model.objects.get.return_value

        response, in_use_check = self._delete(CURATOR_CONFIG, in_use=False)

        self.assertEqual(response.status_code, 200)
        in_use_check.assert_called_once_with(CURATOR_CONFIG)
        stored.delete.assert_called_once_with()
        self.assertEqual(body_of(response), {"deleted": "serialized-row"})
        self.serializer.return_value.serialize.assert_called_once_with(stored)
