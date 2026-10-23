"""``GET /iiif/v3/content-state/<analysis>/<feature>``: the published IIIF Content State of one analysis zone.

Usage:
    python manage.py test tests.test_iiif_content_state --settings=tests.test_settings
"""

import json
import uuid

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.test import Client

from arches.app.utils.permission_backend import assign_perm

from tests import iiif_jsonld
from tests.explorer_fixtures import CANVAS, CANVAS_3, FEATURES, IIIFCase
from tests.iiif_schema import assert_valid_iiif

BASE = settings.PUBLIC_SERVER_ADDRESS
PROFILE = 'application/ld+json;profile="http://iiif.io/api/presentation/3/context.json"'
OA = "http://www.w3.org/ns/oa#"
PUBLIC = "public, no-cache"
PRIVATE = "private, no-store"


class ContentStateCase(IIIFCase):
    def setUp(self):
        super().setUp()
        self.visitor = Client()

    def url(self, key="open", feature=None):
        analysis = self.analyses[key].pk
        return f"/iiif/v3/content-state/{analysis}/{feature or FEATURES[key]}"

    def manifest_of(self, key):
        return f"{BASE}iiif/v3/explorer-manifest?ids=an:{self.analyses[key].pk}:-"


class ContentStateTests(ContentStateCase):
    def test_the_state_targets_the_zone_on_its_canvas_within_the_analysis_manifest(
        self,
    ):
        state = self.visitor.get(self.url()).json()

        self.assertEqual(state["id"], BASE + self.url().lstrip("/"))
        self.assertEqual(state["type"], "Annotation")
        self.assertEqual(state["motivation"], ["contentState"])
        target = state["target"]
        self.assertEqual(target["type"], "SpecificResource")
        self.assertEqual(
            target["source"],
            {
                "id": CANVAS,
                "type": "Canvas",
                "partOf": [{"id": self.manifest_of("open"), "type": "Manifest"}],
            },
        )
        self.assertEqual(
            [s["type"] for s in target["selector"]], ["PointSelector", "SvgSelector"]
        )

    def test_a_rectangle_zone_is_an_xywh_fragment_on_its_own_canvas(self):
        state = self.visitor.get(
            self.url("on_document", FEATURES["on_document_3"])
        ).json()

        self.assertEqual(state["target"]["source"]["id"], CANVAS_3)
        self.assertEqual(state["target"]["selector"]["type"], "FragmentSelector")
        self.assertTrue(state["target"]["selector"]["value"].startswith("xywh="))

    def test_the_state_is_valid_iiif_and_json_ld(self):
        state = self.visitor.get(self.url()).json()

        self.assertEqual(state["@context"], iiif_jsonld.PRESENTATION_3)
        assert_valid_iiif(self, state)
        (expanded,) = iiif_jsonld.expand_presentation(state)
        self.assertEqual(expanded["@id"], state["id"])
        self.assertEqual(expanded["@type"], [f"{OA}Annotation"])
        self.assertEqual(
            expanded[f"{OA}motivatedBy"],
            [{"@id": "http://iiif.io/api/presentation/3#contentState"}],
        )
        (target,) = expanded[f"{OA}hasTarget"]
        (source,) = target[f"{OA}hasSource"]
        self.assertEqual(source["@id"], CANVAS)
        self.assertEqual(
            source["http://purl.org/dc/terms/isPartOf"][0]["@id"],
            self.manifest_of("open"),
        )

    def test_download_adds_an_attachment_disposition_and_keeps_the_id(self):
        plain = self.visitor.get(self.url())
        download = self.visitor.get(self.url() + "?download=1")

        self.assertEqual(download.status_code, 200)
        self.assertNotIn("Content-Disposition", plain)
        disposition = download["Content-Disposition"]
        self.assertTrue(disposition.startswith("attachment;"), disposition)
        self.assertIn(".content-state.json", disposition)
        self.assertEqual(json.loads(download.content), json.loads(plain.content))

    def test_the_state_answers_with_cors_and_the_ld_json_profile_type(self):
        response = self.visitor.get(self.url(), HTTP_ORIGIN="https://viewer.example")

        self.assertEqual(response["Content-Type"], PROFILE)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertEqual(response["Cache-Control"], PUBLIC)
        self.assertTrue(response["ETag"])

    def test_the_route_is_language_neutral_and_resolves_the_minted_id(self):
        from django.urls import resolve

        from manuspectrum.iiif import ids

        minted = ids.content_state(self.analyses["open"].pk, FEATURES["open"])
        self.assertEqual(
            resolve("/" + minted[len(BASE) :]).url_name, "iiif-v3-content-state"
        )


class ContentStateMatrixTests(ContentStateCase):
    def setUp(self):
        super().setUp()
        self.reader = Client()
        self.reader.force_login(self.editor)
        stranger = User.objects.create_user("state_stranger", password="pw")
        stranger.groups.add(Group.objects.get(name="Resource Editor"))
        assign_perm("no_access_to_resourceinstance", stranger, self.analyses["open"])
        self.stranger = Client()
        self.stranger.force_login(stranger)

    def test_the_visitor_reads_a_visible_zone(self):
        response = self.visitor.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], PUBLIC)

    def test_a_hidden_analysis_is_401_to_the_visitor(self):
        self.embargo(self.analyses["open"])

        response = self.visitor.get(self.url())

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Cache-Control"], PRIVATE)
        self.assertIn("Bearer", response["WWW-Authenticate"])
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        body = response.json()
        self.assertEqual(body["id"], BASE + self.url().lstrip("/"))
        self.assertEqual(body["type"], "Annotation")

    def test_a_granted_session_reads_a_hidden_analysis_privately(self):
        self.embargo(self.analyses["open"])

        response = self.reader.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], PRIVATE)
        self.assertEqual(response.json()["motivation"], ["contentState"])

    def test_an_ungranted_session_is_a_bodyless_403(self):
        response = self.stranger.get(self.url())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.content, b"")

    def test_an_unknown_analysis_is_a_bodyless_404(self):
        response = self.visitor.get(
            f"/iiif/v3/content-state/{uuid.uuid4()}/{FEATURES['open']}"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")

    def test_a_feature_of_another_analysis_is_404(self):
        response = self.visitor.get(self.url("open", FEATURES["on_document_1"]))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
