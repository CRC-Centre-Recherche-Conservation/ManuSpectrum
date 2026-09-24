"""What the Explorer shows to whom, decided once by ``visible_set``.

Usage:
    python manage.py test tests.test_explorer_visibility --settings="tests.test_settings"
"""

from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.cache import cache
from django.test import TestCase

from manuspectrum.utils.public_visibility import (
    draft_state_id_set,
    is_connected,
    reader_scope,
)

DEFAULT_LIFECYCLE_DRAFT = "9375c9a7-dad2-4f14-a5c1-d7e329fdde4f"
DEFAULT_LIFECYCLE_ACTIVE = "f75bb034-36e3-4ab4-8167-f520cf0b4c58"


class ReaderTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_the_anonymous_row_is_not_connected(self):
        anonymous = User.objects.get(username="anonymous")

        self.assertTrue(anonymous.is_authenticated)
        self.assertFalse(is_connected(anonymous))
        self.assertEqual(reader_scope(anonymous), "anonymous")

    def test_django_anonymous_user_is_not_connected(self):
        self.assertFalse(is_connected(AnonymousUser()))
        self.assertEqual(reader_scope(AnonymousUser()), "anonymous")

    def test_a_signed_in_editor_is_connected_and_keyed_by_id(self):
        editor = User.objects.create_user("explorer_editor", password="pw")
        editor.groups.add(Group.objects.get(name="Resource Editor"))

        self.assertTrue(is_connected(editor))
        self.assertEqual(reader_scope(editor), str(editor.pk))

    def test_the_initial_state_of_the_default_lifecycle_is_a_draft(self):
        drafts = draft_state_id_set()

        self.assertIn(DEFAULT_LIFECYCLE_DRAFT, drafts)
        self.assertNotIn(DEFAULT_LIFECYCLE_ACTIVE, drafts)
