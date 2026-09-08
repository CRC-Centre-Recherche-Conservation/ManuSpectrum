"""Guards for the normalize_list_item_languages command.

The command rewrites language codes in place, so the tests that matter are the
ones pinning what it must NOT touch: genuine translations in other languages,
and any fold that would collide with an existing prefLabel.
"""

import uuid

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from arches.app.models.models import Language
from arches_controlled_lists.models import List, ListItem, ListItemValue


def _language(code):
    # The test database only seeds part of the language table, and the codes
    # this command folds are exactly the ones a bare install may not carry.
    Language.objects.get_or_create(
        code=code,
        defaults={"name": code, "default_direction": "ltr", "scope": "system"},
    )
    return code


def _item(sortorder=0):
    controlled_list = List.objects.create(id=uuid.uuid4(), name=str(uuid.uuid4()))
    return ListItem.objects.create(
        id=uuid.uuid4(),
        uri=f"https://example.org/{uuid.uuid4()}",
        list=controlled_list,
        sortorder=sortorder,
    )


def _label(item, language, value="label", valuetype="prefLabel"):
    return ListItemValue.objects.create(
        id=uuid.uuid4(),
        list_item=item,
        valuetype_id=valuetype,
        language_id=_language(language),
        value=value,
    )


class NormalizeListItemLanguagesTests(TestCase):
    def _run(self, **kwargs):
        out = StringIO()
        call_command("normalize_list_item_languages", stdout=out, **kwargs)
        return out.getvalue()

    def test_folds_the_three_regional_variants(self):
        item = _item()
        fr_fr = _label(item, "fr-FR", "matériau")
        en_us = _label(item, "en-US", "material", valuetype="altLabel")
        en_uk = _label(item, "en-UK", "note", valuetype="scopeNote")

        self._run()

        self.assertEqual(ListItemValue.objects.get(pk=fr_fr.pk).language_id, "fr")
        self.assertEqual(ListItemValue.objects.get(pk=en_us.pk).language_id, "en")
        self.assertEqual(ListItemValue.objects.get(pk=en_uk.pk).language_id, "en")

    def test_leaves_genuine_translations_alone(self):
        # German and Spanish are not variants of the site's languages: they are
        # real thesaurus content and folding them would lose it.
        item = _item()
        de = _label(item, "de", "Werkstoff")
        es = _label(item, "es", "material", valuetype="altLabel")

        self._run()

        self.assertEqual(ListItemValue.objects.get(pk=de.pk).language_id, "de")
        self.assertEqual(ListItemValue.objects.get(pk=es.pk).language_id, "es")

    def test_skips_a_preflabel_that_would_collide(self):
        # unique_item_preflabel_language forbids two prefLabels in one language,
        # and choosing which one wins is not this command's call.
        item = _item()
        _label(item, "en", "material")
        en_us = _label(item, "en-US", "material (US)")

        output = self._run()

        self.assertEqual(ListItemValue.objects.get(pk=en_us.pk).language_id, "en-US")
        self.assertIn("already holds a prefLabel", output)

    def test_a_colliding_preflabel_does_not_block_other_valuetypes(self):
        # An altLabel may share the language with a prefLabel, so it must still fold.
        item = _item()
        _label(item, "en", "material")
        alt = _label(item, "en-US", "stuff", valuetype="altLabel")

        self._run()

        self.assertEqual(ListItemValue.objects.get(pk=alt.pk).language_id, "en")

    def test_dry_run_changes_nothing(self):
        item = _item()
        fr_fr = _label(item, "fr-FR", "matériau")

        output = self._run(dry_run=True)

        self.assertEqual(ListItemValue.objects.get(pk=fr_fr.pk).language_id, "fr-FR")
        self.assertIn("Dry run", output)

    def test_is_idempotent(self):
        item = _item()
        _label(item, "fr-FR", "matériau")

        self._run()
        output = self._run()

        self.assertIn("Nothing to do", output)
