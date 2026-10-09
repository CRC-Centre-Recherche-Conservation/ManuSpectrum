"""The family rule of the map's Materials control.

Usage:
    python manage.py test tests.test_explorer_material_families --settings="tests.test_settings"
"""

from arches_controlled_lists.models import List, ListItem
from django.test import SimpleTestCase, TestCase

from manuspectrum.views.explorer.material_families import (
    FAMILIES,
    FAMILY_TABLE,
    INHA,
    families_of,
    family_from_chains,
)

VERMILION = INHA + "9deb5cac-1edb-4874-812a-1a280d35f9ba"
RED_PIGMENT = INHA + "b7238344-724a-44ec-8820-b2944fe2a908"
PIGMENT = INHA + "8504701f-8c28-4817-a7af-4318c57c12ef"
COLORING = INHA + "be9d6215-4940-4fac-911e-4862ba53e2b0"
SYNTHETIC = INHA + "290a2c55-0f79-4794-9f67-5b4d967f4364"
SYNTHETIC_COLORING = INHA + "f094f107-a4a9-487a-a4be-d99f07b58838"
BUCKTHORN = INHA + "546a09f8-5fd6-4adc-ba0b-738fcce68a09"
LAKE = INHA + "ab5c36eb-f323-4441-9f74-e6d9d7fa7e3a"
GREEN_PIGMENT = INHA + "34caadcb-6fc1-47ec-8bd8-83810c1ebba9"
GOLD = INHA + "983dc56b-54f0-4b4a-80cf-9c45fd67cbf4"
YELLOW_PIGMENT = INHA + "f647c688-1f6e-4160-af75-83a4db27ef24"
EGG_WHITE = INHA + "f2038022-3d3d-444f-98e3-86c0f4a28a46"
EGG = INHA + "d1713997-db6c-4249-b17e-22fc1d1fdb74"


class FamilyFromChainsTests(SimpleTestCase):
    def test_a_term_repeated_under_two_branches_takes_its_colouring_material_family(
        self,
    ):
        chains = [
            [VERMILION, SYNTHETIC_COLORING, SYNTHETIC],
            [VERMILION, RED_PIGMENT, PIGMENT, COLORING],
        ]
        self.assertEqual(family_from_chains(chains), "red")

    def test_a_lake_that_is_also_a_green_pigment_is_green(self):
        chains = [
            [BUCKTHORN, LAKE, COLORING],
            [BUCKTHORN, GREEN_PIGMENT, PIGMENT, COLORING],
        ]
        self.assertEqual(family_from_chains(chains), "green")

    def test_an_explicit_metal_wins_over_a_colour_branch(self):
        self.assertEqual(
            family_from_chains([[GOLD, YELLOW_PIGMENT, PIGMENT, COLORING]]), "metals"
        )

    def test_a_binder_is_found_through_its_parent(self):
        self.assertEqual(family_from_chains([[EGG_WHITE, EGG]]), "binders")

    def test_a_term_outside_the_table_or_no_chain_is_other(self):
        self.assertEqual(
            family_from_chains([["http://localhost:8000/plugins/x"]]), "other"
        )
        self.assertEqual(family_from_chains([]), "other")

    def test_the_table_names_known_families_once_per_uri_and_other_closes_the_list(
        self,
    ):
        self.assertEqual(FAMILIES[-1], "other")
        self.assertTrue({family for _, family in FAMILY_TABLE} <= set(FAMILIES))
        uris = [uri for uri, _ in FAMILY_TABLE]
        self.assertEqual(len(uris), len(set(uris)))


class FamiliesOfTests(TestCase):
    def test_every_occurrence_of_a_uri_is_read_and_an_unknown_uri_is_other(self):
        agorha = List.objects.create(name="AGORHA materials")
        coloring = ListItem.objects.create(list=agorha, uri=COLORING, sortorder=0)
        pigment = ListItem.objects.create(
            list=agorha, uri=PIGMENT, sortorder=0, parent=coloring
        )
        red = ListItem.objects.create(
            list=agorha, uri=RED_PIGMENT, sortorder=0, parent=pigment
        )
        synthetic = ListItem.objects.create(list=agorha, uri=SYNTHETIC, sortorder=1)
        synthetic_coloring = ListItem.objects.create(
            list=agorha, uri=SYNTHETIC_COLORING, sortorder=0, parent=synthetic
        )
        ListItem.objects.create(
            list=agorha, uri=VERMILION, sortorder=0, parent=synthetic_coloring
        )
        ListItem.objects.create(list=agorha, uri=VERMILION, sortorder=0, parent=red)

        self.assertEqual(
            families_of([VERMILION, "http://vocab/unknown", ""]),
            {VERMILION: "red", "http://vocab/unknown": "other"},
        )

    def test_no_uri_reads_nothing(self):
        with self.assertNumQueries(0):
            self.assertEqual(families_of([]), {})
