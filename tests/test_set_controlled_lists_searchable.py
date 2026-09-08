"""Guards for the set_controlled_lists_searchable command.

The point of the command is that it goes through `save()` rather than
`bulk_update`, because that is what indexes the list. These tests pin the
selection logic; the indexing itself belongs to arches_controlled_lists.
"""

import uuid

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from arches_controlled_lists.models import List


def _list(searchable=False):
    return List.objects.create(
        id=uuid.uuid4(), name=str(uuid.uuid4()), searchable=searchable
    )


class SetControlledListsSearchableTests(TestCase):
    def _run(self, **kwargs):
        out = StringIO()
        # index()/delete_index() talk to Elasticsearch; the command's contract is
        # that it routes through save(), which is asserted separately below.
        with mock.patch.object(List, "index"), mock.patch.object(List, "delete_index"):
            call_command("set_controlled_lists_searchable", stdout=out, **kwargs)
        return out.getvalue()

    def test_turns_every_list_on(self):
        first, second = _list(), _list()

        self._run()

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.searchable)
        self.assertTrue(second.searchable)

    def test_off_turns_them_back(self):
        controlled_list = _list(searchable=True)

        self._run(off=True)

        controlled_list.refresh_from_db()
        self.assertFalse(controlled_list.searchable)

    def test_restricts_to_the_given_ids(self):
        targeted, untouched = _list(), _list()

        self._run(list_ids=[str(targeted.pk)])

        targeted.refresh_from_db()
        untouched.refresh_from_db()
        self.assertTrue(targeted.searchable)
        self.assertFalse(untouched.searchable)

    def test_dry_run_changes_nothing(self):
        controlled_list = _list()

        output = self._run(dry_run=True)

        controlled_list.refresh_from_db()
        self.assertFalse(controlled_list.searchable)
        self.assertIn("Dry run", output)

    def test_skips_lists_already_in_the_requested_state(self):
        _list(searchable=True)

        output = self._run()

        self.assertIn("Nothing to do", output)

    def test_goes_through_save_so_the_index_follows(self):
        # bulk_update would flip the column without indexing, leaving the flag
        # and the index disagreeing — that is the bug this command exists to avoid.
        _list()

        with mock.patch.object(List, "index") as index:
            call_command("set_controlled_lists_searchable", stdout=StringIO())

        index.assert_called_once()
