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
