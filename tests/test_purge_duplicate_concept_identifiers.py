"""Guards for the purge_duplicate_concept_identifiers command.

The command deletes rows, so what matters is not that it removes the redundant
duplicates — it is that it refuses to remove anything else. Each test below
pins one of the three cases it must leave alone.
"""

import uuid

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from arches.app.models.models import Concept, Value


def _concept():
    return Concept.objects.create(
        conceptid=uuid.uuid4(), nodetype_id="Concept", legacyoid=str(uuid.uuid4())
    )


def _identifier(concept, text):
    return Value.objects.create(
        valueid=uuid.uuid4(),
        concept=concept,
        valuetype_id="identifier",
        value=text,
        language_id="en",
    )


URI = "https://ark.frantiq.fr/ark:/26678/crtxhXbaDgYSc"


class PurgeDuplicateConceptIdentifiersTests(TestCase):
    def _run(self, **kwargs):
        out = StringIO()
        call_command("purge_duplicate_concept_identifiers", stdout=out, **kwargs)
        return out.getvalue()

    def test_removes_the_serialised_dict_and_keeps_the_uri(self):
        concept = _concept()
        stray = _identifier(concept, f"{{'id': '{uuid.uuid4()}', 'value': '{URI}'}}")
        kept = _identifier(concept, URI)

        self._run()

        self.assertFalse(Value.objects.filter(pk=stray.pk).exists())
        self.assertTrue(Value.objects.filter(pk=kept.pk).exists())

    def test_dry_run_changes_nothing(self):
        concept = _concept()
        stray = _identifier(concept, f"{{'id': '{uuid.uuid4()}', 'value': '{URI}'}}")
        _identifier(concept, URI)

        output = self._run(dry_run=True)

        self.assertTrue(Value.objects.filter(pk=stray.pk).exists())
        self.assertIn("Dry run", output)

    def test_keeps_a_dict_whose_inner_value_differs(self):
        # A divergent dict may be the only carrier of that other URI; discarding
        # it would lose information the command cannot recover.
        concept = _concept()
        stray = _identifier(
            concept, f"{{'id': '{uuid.uuid4()}', 'value': 'https://example.org/other'}}"
        )
        _identifier(concept, URI)

        self._run()

        self.assertTrue(Value.objects.filter(pk=stray.pk).exists())

    def test_keeps_a_dict_that_is_the_concepts_only_identifier(self):
        # Deleting it would leave the concept with no identifier at all.
        concept = _concept()
        stray = _identifier(concept, f"{{'id': '{uuid.uuid4()}', 'value': '{URI}'}}")

        self._run()

        self.assertTrue(Value.objects.filter(pk=stray.pk).exists())

    def test_keeps_an_unparsable_dict(self):
        concept = _concept()
        stray = _identifier(concept, "{this is not a python literal")
        _identifier(concept, URI)

        self._run()

        self.assertTrue(Value.objects.filter(pk=stray.pk).exists())

    def test_is_idempotent(self):
        concept = _concept()
        _identifier(concept, f"{{'id': '{uuid.uuid4()}', 'value': '{URI}'}}")
        _identifier(concept, URI)

        self._run()
        output = self._run()

        self.assertIn("Nothing to do", output)
