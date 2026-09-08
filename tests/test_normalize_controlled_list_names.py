"""Guards for the normalize_controlled_list_names command.

`List.name` holds a single string with no per-language variant, so the choice
this command makes is final until someone runs it again. The tests pin the
preference order and the cases where it must keep its hands off.
"""

import uuid

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from arches.app.models.models import Concept, Language, Value
from arches_controlled_lists.models import List


def _language(code):
    Language.objects.get_or_create(
        code=code,
        defaults={"name": code, "default_direction": "ltr", "scope": "system"},
    )
    return code


def _list_with_labels(current_name, labels):
    """A list whose id is its source collection's conceptid, as the conversion leaves it."""
    concept = Concept.objects.create(
        conceptid=uuid.uuid4(),
        nodetype_id="Collection",
        legacyoid=str(uuid.uuid4()),
    )
    for language, value in labels.items():
        Value.objects.create(
            valueid=uuid.uuid4(),
            concept=concept,
            valuetype_id="prefLabel",
            language_id=_language(language),
            value=value,
        )
    return List.objects.create(id=concept.pk, name=current_name)


class NormalizeControlledListNamesTests(TestCase):
    def _run(self, **kwargs):
        out = StringIO()
        call_command("normalize_controlled_list_names", stdout=out, **kwargs)
        return out.getvalue()

    def test_prefers_english_over_the_current_name(self):
        controlled_list = _list_with_labels(
            "10.1. offizielle Berufe und Funktionen",
            {"de": "10.1. offizielle Berufe und Funktionen", "en": "official role"},
        )

        self._run()

        controlled_list.refresh_from_db()
        self.assertEqual(controlled_list.name, "official role")

    def test_falls_back_to_french_when_english_is_missing(self):
        controlled_list = _list_with_labels(
            "volkeren", {"nl": "volkeren", "fr": "peuples"}
        )

        self._run()

        controlled_list.refresh_from_db()
        self.assertEqual(controlled_list.name, "peuples")

    def test_falls_back_to_any_label_when_neither_is_present(self):
        controlled_list = _list_with_labels("", {"ar": "شعوب"})

        self._run()

        controlled_list.refresh_from_db()
        self.assertEqual(controlled_list.name, "شعوب")

    def test_leaves_a_list_already_named_in_english_alone(self):
        controlled_list = _list_with_labels("AAT - Genders", {"en": "AAT - Genders"})

        output = self._run()

        controlled_list.refresh_from_db()
        self.assertEqual(controlled_list.name, "AAT - Genders")
        self.assertIn("Nothing to rename", output)

    def test_warns_when_two_lists_would_end_up_sharing_a_name(self):
        _list_with_labels("first", {"en": "duplicate"})
        _list_with_labels("second", {"en": "duplicate"})

        output = self._run(dry_run=True)

        self.assertIn("would be shared by several lists", output)

    def test_dry_run_changes_nothing(self):
        controlled_list = _list_with_labels("volkeren", {"en": "Peoples"})

        output = self._run(dry_run=True)

        controlled_list.refresh_from_db()
        self.assertEqual(controlled_list.name, "volkeren")
        self.assertIn("Dry run", output)

    def test_is_idempotent(self):
        _list_with_labels("volkeren", {"en": "Peoples"})

        self._run()
        output = self._run()

        self.assertIn("Nothing to rename", output)
