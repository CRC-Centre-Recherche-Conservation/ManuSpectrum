from django.test import SimpleTestCase, override_settings

from manuspectrum.checks import (
    check_contact_email,
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
