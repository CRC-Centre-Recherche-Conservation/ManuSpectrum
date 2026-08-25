"""The guard that stops a renderer configuration being deleted while in use.

It never fired. It asked a single hard-coded nodegroup id inherited from Arches
for Science — present in no ManuSpectrum graph — and only inspected entry ``0``
of a file-list value. So it answered "not in use" for every configuration ever
created, and a configuration could be deleted out from under the files
referencing it, leaving them pointing at nothing.

These tests lock both halves: every ``file-list`` node is asked, and a match is
found wherever the entry sits in the array. A measurement tile routinely holds
two files — the instrument's original and the CSV derivative that carries the
configuration — so "entry 0 only" is not a rare edge case here, it is the
common shape.
"""

from django.test import SimpleTestCase
from django.urls import resolve
from django.urls.exceptions import Resolver404

from manuspectrum.constants.xy_presets import is_seeded_preset
from manuspectrum.views.renderer_config import in_use_query

CONFIG_ID = "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a03"
MEASUREMENT_NODE = "8fe5161a-7bf2-11ef-b1e5-dd514ecd97bc"
IMAGERY_NODE = "52a4f230-7bf6-11ef-b1e5-dd514ecd97bc"


def rendered(query):
    """The lookups a Q resolves to, as a flat list of (path, value) pairs."""
    pairs = []
    for child in query.children:
        if hasattr(child, "children"):
            pairs.extend(rendered(child))
        else:
            pairs.append(child)
    return pairs


class InUseQueryTests(SimpleTestCase):
    def test_asks_every_file_node(self):
        query = in_use_query(
            CONFIG_ID,
            [(MEASUREMENT_NODE, MEASUREMENT_NODE), (IMAGERY_NODE, IMAGERY_NODE)],
        )
        paths = [path for path, _ in rendered(query)]

        for node in (MEASUREMENT_NODE, IMAGERY_NODE):
            self.assertIn(f"data__{node}__contains", paths)

    def test_matches_an_entry_at_any_position(self):
        query = in_use_query(CONFIG_ID, [(MEASUREMENT_NODE, MEASUREMENT_NODE)])
        paths = [path for path, _ in rendered(query)]

        # Containment over the whole array, never a fixed index.
        self.assertIn(f"data__{MEASUREMENT_NODE}__contains", paths)
        self.assertFalse(
            [path for path in paths if "__0__" in path],
            msg="the guard is looking at a fixed entry position again",
        )

    def test_looks_for_the_configuration_it_was_given(self):
        query = in_use_query(CONFIG_ID, [(MEASUREMENT_NODE, MEASUREMENT_NODE)])
        values = [value for path, value in rendered(query) if "contains" in path]

        self.assertEqual(values, [[{"rendererConfig": CONFIG_ID}]])

    def test_no_file_node_yields_an_empty_query(self):
        # An empty Q matches everything, which would report every configuration
        # as in use and block all deletion. The caller short-circuits instead.
        self.assertFalse(in_use_query(CONFIG_ID, []))


class SeededPresetIdentityTests(SimpleTestCase):
    """The guard's acceptance set must match the one the database resolves.

    Both protections on a seeded preset — superuser-only editing, no deletion
    at all — are decided by comparing a string against canonical UUID literals.
    The value compared is the raw URL segment, and the same raw segment then
    reaches ``RendererConfig.objects.get(configid=...)``, where Django's
    UUIDField funnels it through ``uuid.UUID(hex=...)``: case-insensitive, and
    tolerant of missing hyphens, braces and a ``urn:uuid:`` prefix.

    So the two disagreed. ``7A1C…`` returned False from the guard while
    resolving the protected row, and any editor could rewrite or delete the
    shared baseline every technique-derived configuration points at.

    The in-use interlock failed the same way and in the same direction:
    JSONB containment is byte-exact, tile data always holds the canonical
    lowercase form, so a non-canonical id matched zero files and the delete was
    not merely permitted but guaranteed to complete.
    """

    SEEDED = "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a02"

    def test_a_seeded_preset_is_recognised_however_it_is_spelled(self):
        for spelling in (
            self.SEEDED,
            self.SEEDED.upper(),
            self.SEEDED.replace("-", ""),
            "{" + self.SEEDED + "}",
            "urn:uuid:" + self.SEEDED,
        ):
            self.assertTrue(
                is_seeded_preset(spelling),
                msg=f"{spelling} resolves to a protected row but skips the guard",
            )

    def test_a_curator_configuration_stays_unprotected(self):
        self.assertFalse(is_seeded_preset("11111111-2222-3333-4444-555555555555"))

    def test_a_value_that_is_not_a_uuid_is_not_protected(self):
        # The guard answers "not seeded" rather than raising: the row lookup
        # that follows is what should reject a malformed id.
        for junk in ("", "not-a-uuid", None, 42):
            self.assertFalse(is_seeded_preset(junk))

    def test_the_in_use_lookup_asks_in_the_form_tiles_store(self):
        # Tile data always carries the canonical lowercase spelling, and JSONB
        # containment is byte-exact, so the query has to canonicalise too.
        query = in_use_query(
            self.SEEDED.upper(), [(MEASUREMENT_NODE, MEASUREMENT_NODE)]
        )
        self.assertIn(self.SEEDED, str(query))


class ConfigIdRoutingTests(SimpleTestCase):
    """The URL must admit the one spelling the guard recognises.

    Second layer, deliberately redundant with the canonicalisation above: the
    protection on a seeded preset should not rest on a single comparison being
    written correctly.
    """

    SEEDED = "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a02"

    def test_the_canonical_form_reaches_the_view(self):
        match = resolve(f"/renderer_config/{self.SEEDED}")
        self.assertEqual(str(match.kwargs["renderer_config_id"]), self.SEEDED)

    def test_every_other_spelling_is_refused_at_the_door(self):
        for spelling in (
            self.SEEDED.upper(),
            self.SEEDED.replace("-", ""),
            "{" + self.SEEDED + "}",
            "urn:uuid:" + self.SEEDED,
            "not-a-uuid",
        ):
            with self.assertRaises(
                Resolver404, msg=f"{spelling} still reaches the view"
            ):
                resolve(f"/renderer_config/{spelling}")

    def test_the_create_route_still_takes_no_id(self):
        # Anchored, so a rejected id cannot fall through here and silently
        # become "create a new configuration".
        match = resolve("/renderer_config/")
        self.assertIsNone(match.kwargs.get("renderer_config_id"))
