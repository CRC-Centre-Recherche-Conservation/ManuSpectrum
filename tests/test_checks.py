from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from manuspectrum.checks import (
    check_contact_email,
    check_published_graph_languages,
    effective_contact_email,
    is_placeholder_email,
)


class PlaceholderDetectionTests(SimpleTestCase):
    def test_factory_placeholder_variants(self):
        for addr in (
            "xxxx@xxx.com",
            "XXXX@XXX.COM",
            "x@x",
            "xx@xxxx.fr",
            "contact@example.com",
            "noreply@example.org",
        ):
            self.assertTrue(is_placeholder_email(addr), addr)

    def test_real_addresses_pass(self):
        for addr in (
            "team@manuspectrum.fr",
            "anne.michelin@mnhn.fr",
            "xavier@crc.fr",  # starts with x but is a real address
        ):
            self.assertFalse(is_placeholder_email(addr), addr)

    def test_empty_is_not_a_placeholder(self):
        # "no address configured" is a designed state, not a misconfiguration
        self.assertFalse(is_placeholder_email(""))
        self.assertFalse(is_placeholder_email(None))


class EffectiveContactEmailTests(SimpleTestCase):
    @override_settings(CONTACT_EMAIL="a@b.fr", DEFAULT_FROM_EMAIL="c@d.fr")
    def test_prefers_contact_email(self):
        self.assertEqual(effective_contact_email(), "a@b.fr")

    @override_settings(CONTACT_EMAIL="", DEFAULT_FROM_EMAIL="c@d.fr")
    def test_falls_back_to_default_from_email(self):
        self.assertEqual(effective_contact_email(), "c@d.fr")


class ContactEmailCheckTests(SimpleTestCase):
    @override_settings(CONTACT_EMAIL="", DEFAULT_FROM_EMAIL="xxxx@xxx.com", DEBUG=False)
    def test_factory_default_is_an_error_in_prod(self):
        # The exact shipped-settings scenario: CONTACT_EMAIL unset, the tag
        # falls back to the factory DEFAULT_FROM_EMAIL placeholder.
        messages = check_contact_email(None)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].id, "manuspectrum.E001")

    @override_settings(CONTACT_EMAIL="", DEFAULT_FROM_EMAIL="xxxx@xxx.com", DEBUG=True)
    def test_factory_default_is_a_warning_in_dev(self):
        messages = check_contact_email(None)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].id, "manuspectrum.W001")

    @override_settings(
        CONTACT_EMAIL="team@manuspectrum.fr",
        DEFAULT_FROM_EMAIL="xxxx@xxx.com",
        DEBUG=False,
    )
    def test_real_contact_email_silences_the_check(self):
        self.assertEqual(check_contact_email(None), [])

    @override_settings(CONTACT_EMAIL="", DEFAULT_FROM_EMAIL="", DEBUG=False)
    def test_no_address_at_all_is_accepted(self):
        # Designed fallback: the contact page disables its button.
        self.assertEqual(check_contact_email(None), [])


class PublishedGraphLanguageCheckTests(TestCase):
    def test_check_runs_cleanly(self):
        # Smoke: the DB-tagged check must return a list and never raise, even
        # on a database with no resources (the test DB).
        from manuspectrum.checks import check_published_graph_languages

        result = check_published_graph_languages(None, databases=["default"])
        self.assertIsInstance(result, list)


def _publication_tables(graph_pubs, resource_pubs, published_per_language):
    """Stand-ins for the three Arches managers the language check reads.

    ``check_published_graph_languages`` imports them inside its own body, so
    patching them on ``arches.app.models.models`` reaches the call.
    """
    graph_model = mock.Mock()
    graph_model.objects.filter.return_value.values_list.return_value = graph_pubs

    resource_instance = mock.Mock()
    resource_instance.objects.exclude.return_value.values_list.return_value.distinct.return_value = (
        resource_pubs
    )

    published_graph = mock.Mock()

    def published_in(language, publication_id__in):
        row = mock.Mock()
        row.values_list.return_value = published_per_language.get(language, [])
        return row

    published_graph.objects.filter.side_effect = published_in

    return mock.patch.multiple(
        "arches.app.models.models",
        GraphModel=graph_model,
        ResourceInstance=resource_instance,
        PublishedGraph=published_graph,
    )


PUB_A = "11111111-1111-4111-8111-111111111111"
PUB_B = "22222222-2222-4222-8222-222222222222"


@override_settings(LANGUAGES=[("en", "English"), ("fr", "French")])
class PublishedGraphLanguageGateTests(SimpleTestCase):
    """The migrate-time gate that catches a language activated after publishing.

    Arches serialises each graph per language at publication time, so a
    language added later has no rows and every page under its prefix 500s. The
    check is what turns that into a warning on `migrate` instead of a stack
    trace in production.
    """

    def test_language_without_a_serialisation_is_reported(self):
        with _publication_tables(
            graph_pubs=[PUB_A, PUB_B],
            resource_pubs=[],
            published_per_language={"en": [PUB_A, PUB_B], "fr": [PUB_A]},
        ):
            messages = check_published_graph_languages(None, databases=["default"])

        self.assertEqual([m.id for m in messages], ["manuspectrum.W002"])
        self.assertIn("'fr'", messages[0].msg)
        self.assertIn("1 graph publication(s)", messages[0].msg)
        self.assertIn("i18n synclanguages", messages[0].msg)

    def test_fully_serialised_languages_are_silent(self):
        with _publication_tables(
            graph_pubs=[PUB_A, PUB_B],
            resource_pubs=[],
            published_per_language={"en": [PUB_A, PUB_B], "fr": [PUB_A, PUB_B]},
        ):
            self.assertEqual(
                check_published_graph_languages(None, databases=["default"]), []
            )

    def test_every_missing_language_gets_its_own_message(self):
        with _publication_tables(
            graph_pubs=[PUB_A],
            resource_pubs=[],
            published_per_language={},
        ):
            messages = check_published_graph_languages(None, databases=["default"])

        self.assertEqual(len(messages), 2)
        self.assertEqual({m.id for m in messages}, {"manuspectrum.W002"})

    def test_a_publication_pinned_only_by_a_resource_still_counts(self):
        """An older publication no graph points at any more is still loaded.

        Resources keep their own ``graph_publication_id``, so dropping it from
        the set would leave exactly the pages that 500 unreported.
        """
        with _publication_tables(
            graph_pubs=[],
            resource_pubs=[PUB_B],
            published_per_language={"en": [PUB_B], "fr": []},
        ):
            messages = check_published_graph_languages(None, databases=["default"])

        self.assertEqual([m.id for m in messages], ["manuspectrum.W002"])
        self.assertIn("'fr'", messages[0].msg)

    def test_a_half_migrated_database_does_not_block_migrate(self):
        broken = mock.Mock()
        broken.objects.filter.side_effect = RuntimeError("relation does not exist")

        with mock.patch("arches.app.models.models.GraphModel", broken):
            self.assertEqual(
                check_published_graph_languages(None, databases=["default"]), []
            )
