"""Unit tests for the normalize_iconographic_uris management command.

The Component graph is not loaded in the test database, so tiles are
faked and the Tile manager is patched at the command-module level.
"""

import io
import uuid
from unittest.mock import MagicMock, patch

import requests
from django.core.management import call_command
from django.test import TestCase

from manuspectrum.constants.biblissima import COMP_ICONOGRAPHIC_NODE
from manuspectrum.management.commands import normalize_iconographic_uris as cmd
from manuspectrum.views import biblissima_proxy as bp

DESC_HASH = "desc" + "c" * 40
PORTAL_URL = f"{bp.BIBLISSIMA_PORTAL}/{DESC_HASH}"


class FakeTile:
    def __init__(self, url, label="lion", provisional=None, resource_id=None):
        self.tileid = uuid.uuid4()
        self.resourceinstance_id = resource_id or uuid.uuid4()
        self.data = {COMP_ICONOGRAPHIC_NODE: {"url": url, "url_label": label}}
        self.provisionaledits = provisional
        self.save_kwargs = None

    def save(self, **kwargs):
        self.save_kwargs = kwargs


def _p129_response(hash_value=DESC_HASH):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "entities": {
            "Q292273": {
                "claims": {"P129": [{"mainsnak": {"datavalue": {"value": hash_value}}}]}
            }
        }
    }
    return resp


def _run(tiles, apply_changes=False, bib_response=None):
    out = io.StringIO()
    manager = MagicMock()
    manager.filter.return_value = tiles
    with (
        patch.object(cmd, "Tile") as tile_cls,
        patch.object(cmd.bp, "_build_biblissima_session", return_value=MagicMock()),
        patch.object(
            cmd.bp, "_bib_request", return_value=bib_response or _p129_response()
        ),
    ):
        tile_cls.objects = manager
        args = ["--apply"] if apply_changes else []
        call_command("normalize_iconographic_uris", *args, stdout=out)
    return out.getvalue()


class NormalizeIconographicUrisTests(TestCase):
    def test_dry_run_writes_nothing(self):
        tile = FakeTile("https://data.biblissima.fr/entity/Q292273 ")
        output = _run([tile])
        self.assertIsNone(tile.save_kwargs)
        self.assertIn(PORTAL_URL, output)
        self.assertIn("dry-run", output)

    def test_apply_converts_trims_and_keeps_label(self):
        tile = FakeTile("https://data.biblissima.fr/entity/Q292273 ", label="Lion")
        _run([tile], apply_changes=True)
        self.assertEqual(tile.data[COMP_ICONOGRAPHIC_NODE]["url"], PORTAL_URL)
        self.assertEqual(tile.data[COMP_ICONOGRAPHIC_NODE]["url_label"], "Lion")
        self.assertIsNotNone(tile.save_kwargs)
        self.assertIn("transaction_id", tile.save_kwargs)

    def test_already_canonical_tile_is_skipped(self):
        tile = FakeTile(PORTAL_URL)
        _run([tile], apply_changes=True)
        self.assertIsNone(tile.save_kwargs)

    def test_provisional_tile_is_skipped_with_warning(self):
        tile = FakeTile(
            "https://data.biblissima.fr/entity/Q292273",
            provisional={"someuser": {}},
        )
        output = _run([tile], apply_changes=True)
        self.assertIsNone(tile.save_kwargs)
        self.assertIn("provisional", output)

    def test_unparsable_url_warns_without_conversion(self):
        tile = FakeTile("https://example.org/not-biblissima")
        output = _run([tile], apply_changes=True)
        self.assertIsNone(tile.save_kwargs)
        self.assertIn("no parsable QID", output)

    def test_malformed_p129_value_keeps_entity_uri(self):
        entity_url = "https://data.biblissima.fr/entity/Q292273"
        malformed_resp = _p129_response(hash_value="Q12345")

        dry_run_tile = FakeTile(f"{entity_url} ")
        output = _run([dry_run_tile], bib_response=malformed_resp)
        self.assertIsNone(dry_run_tile.save_kwargs)
        self.assertIn(entity_url, output)
        self.assertNotIn(PORTAL_URL, output)

        apply_tile = FakeTile(f"{entity_url} ", label="Lion")
        _run([apply_tile], apply_changes=True, bib_response=malformed_resp)
        self.assertEqual(apply_tile.data[COMP_ICONOGRAPHIC_NODE]["url"], entity_url)
        self.assertIsNotNone(apply_tile.save_kwargs)

    def test_collision_is_reported_in_dry_run(self):
        resource_id = uuid.uuid4()
        entity_tile = FakeTile(
            "https://data.biblissima.fr/entity/Q292273", resource_id=resource_id
        )
        ark_tile = FakeTile(PORTAL_URL, resource_id=resource_id)
        output = _run([entity_tile, ark_tile])
        self.assertIn("collision", output)
