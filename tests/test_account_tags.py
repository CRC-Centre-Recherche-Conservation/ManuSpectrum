from django.test import SimpleTestCase

from manuspectrum.templatetags.account_tags import group_key


class GroupKeyTests(SimpleTestCase):
    def test_groups_by_four(self):
        self.assertEqual(group_key("ABCDEFGHIJ"), "ABCD EFGH IJ")

    def test_empty_values_stay_empty(self):
        self.assertEqual(group_key(None), "")
        self.assertEqual(group_key(""), "")
