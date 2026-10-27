"""Argon2 hashing and the password rules (PP-4, T2)."""

import json

from django.conf import global_settings, settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.core.cache import cache
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.password_validation import password_validators_help_texts
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import translation
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

STRONG = "Gr33n-Lantern!Walks"
OLD_PASSWORD = "Old-Passw0rd!Value"


class PasswordHashingTests(TestCase):
    def test_a_new_password_is_stored_with_argon2(self):
        user = User.objects.create_user("alice", "alice@manuspectrum.test", STRONG)
        self.assertTrue(user.password.startswith("argon2$"), user.password[:12])

    def test_a_pbkdf2_user_signs_in_and_is_rehashed(self):
        user = User.objects.create(
            username="bob",
            email="bob@manuspectrum.test",
            password=make_password(OLD_PASSWORD, hasher="pbkdf2_sha256"),
        )
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        response = Client().post(
            "/en/auth/", {"username": "bob", "password": OLD_PASSWORD}
        )
        self.assertIn(response.status_code, (200, 302))
        user.refresh_from_db()
        self.assertTrue(user.password.startswith("argon2$"), user.password[:12])
        self.assertTrue(user.check_password(OLD_PASSWORD))

    def test_argon2_is_first_and_pbkdf2_stays_in_the_list(self):
        hashers = settings.PASSWORD_HASHERS
        self.assertEqual(hashers[0], "django.contrib.auth.hashers.Argon2PasswordHasher")
        self.assertIn("django.contrib.auth.hashers.PBKDF2PasswordHasher", hashers)

    def test_an_argon2_hash_verifies_under_djangos_default_hashers(self):
        encoded = make_password(STRONG)
        self.assertTrue(encoded.startswith("argon2$"), encoded[:12])
        with override_settings(PASSWORD_HASHERS=global_settings.PASSWORD_HASHERS):
            self.assertTrue(check_password(STRONG, encoded))
            self.assertFalse(check_password(OLD_PASSWORD, encoded))


class PasswordRulesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "marguerite", "marguerite.dupont@manuspectrum.test", OLD_PASSWORD
        )

    def change(self, new_password):
        cache.clear()  # Arches rate-limits auth/password per user
        client = Client()
        client.force_login(self.user)
        response = client.post(
            "/en/auth/password",
            {
                "old_password": OLD_PASSWORD,
                "new_password": new_password,
                "new_password2": new_password,
            },
        )
        return json.loads(response.content)

    def reset(self, new_password):
        client = Client()
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        landing = client.get(f"/en/reset/{uid}/{token}/", follow=True)
        return client.post(
            landing.redirect_chain[-1][0],
            {"new_password1": new_password, "new_password2": new_password},
        )

    def assertRefusedByChange(self, new_password):
        messages = self.change(new_password)
        self.assertTrue(messages["password_validations"], new_password)
        self.assertIsNone(messages["success"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def assertRefusedByReset(self, new_password):
        response = self.reset(new_password)
        self.assertEqual(response.status_code, 200, new_password)
        self.assertTrue(response.context["form"].errors, new_password)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_eleven_characters_are_refused(self):
        self.assertRefusedByChange("Ab1!Ab1!Ab1")
        self.assertRefusedByReset("Ab1!Ab1!Ab1")

    def test_a_common_password_is_refused(self):
        self.assertRefusedByChange("Pe#5gz29ptzmse")
        self.assertRefusedByReset("Pe#5gz29ptzmse")

    def test_a_password_close_to_the_account_is_refused(self):
        self.assertRefusedByChange("Marguerite-1!")
        self.assertRefusedByReset("Marguerite-1!")

    def test_each_missing_class_is_refused(self):
        for password in (
            "lowercase-only-1!x",
            "UPPERCASE-ONLY-1!X",
            "No-digit-here-at-all",
            "NoSymbolHere1234ab",
        ):
            with self.subTest(password=password):
                self.assertRefusedByChange(password)

    def test_any_ascii_punctuation_counts_as_the_symbol(self):
        for symbol in ("-", "_", "~", "+", "=", "[", "?"):
            with self.subTest(symbol=symbol):
                self.assertFalse(
                    self.change(f"Gr33n{symbol}Lantern Walks")["password_validations"]
                )

    def test_a_valid_twelve_character_password_passes(self):
        messages = self.change(STRONG)
        self.assertIsNone(messages["password_validations"], messages)
        self.assertTrue(messages["success"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(STRONG))
        self.assertTrue(self.user.password.startswith("argon2$"))

    def test_the_reset_form_accepts_a_valid_password(self):
        response = self.reset(STRONG)
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(STRONG))


class PasswordHelpTextTests(SimpleTestCase):
    def texts(self, language):
        with translation.override(language):
            return password_validators_help_texts()

    def test_the_length_rule_is_worded_in_french(self):
        texts = self.texts("fr")
        self.assertIn("Au moins 12 caractères", texts)
        self.assertFalse([t for t in texts if "Be longer" in t])

    def test_the_length_rule_is_worded_in_english(self):
        self.assertIn("At least 12 characters", self.texts("en"))
