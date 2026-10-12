"""Self-signup is closed (PP-4, T1).

Arches answers a closed signup with a bare ``Exception``, a 500. The site 404
is nginx's (``tests/test_edge_contract.py``); here Django is checked on its own:
whatever the status, no account is created and no mail leaves.
"""

import time
from urllib.parse import urlencode

from django.contrib.auth.models import Group, User
from django.core import mail
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse

from arches.app.utils.arches_crypto import AESCipher
from arches.app.utils.betterJSONSerializer import JSONSerializer
from django.conf import settings

from manuspectrum.checks import check_signup_closed_in_production

PASSWORD = "Str0ng!Passphrase-for-tests"
FORM = {
    "username": "newcomer",
    "email": "newcomer@manuspectrum.test",
    "first_name": "New",
    "last_name": "Comer",
    "password1": PASSWORD,
    "password2": PASSWORD,
}


def confirmation_link():
    """The link ``SignupView.post`` mails, built the Arches way."""
    userinfo = JSONSerializer().serialize(
        {**FORM, "password1": PASSWORD, "password2": PASSWORD, "ts": int(time.time())}
    )
    link = AESCipher(settings.SECRET_KEY).encrypt(userinfo)
    return reverse("confirm_signup") + "?" + urlencode({"link": link})


class SignupClosedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name=settings.USER_SIGNUP_GROUP)

    def setUp(self):
        self.client = Client(raise_request_exception=False)

    def assertNothingCreated(self, before):
        self.assertEqual(User.objects.count(), before)
        self.assertFalse(User.objects.filter(username=FORM["username"]).exists())
        self.assertEqual(mail.outbox, [])

    def test_setting_is_off(self):
        self.assertIs(settings.ENABLE_USER_SIGNUP, False)

    def test_get_signup_is_refused(self):
        before = User.objects.count()
        response = self.client.get("/en/auth/signup")
        self.assertGreaterEqual(response.status_code, 400)
        self.assertNothingCreated(before)

    def test_post_signup_creates_no_user_and_sends_no_mail(self):
        before = User.objects.count()
        response = self.client.post("/en/auth/signup", FORM)
        self.assertGreaterEqual(response.status_code, 400)
        self.assertNothingCreated(before)

    def test_confirm_signup_with_a_valid_link_creates_no_user(self):
        before = User.objects.count()
        response = self.client.get(confirmation_link())
        self.assertGreaterEqual(response.status_code, 400)
        self.assertNothingCreated(before)

    def test_signup_routes_stay_the_arches_views(self):
        self.assertEqual(
            resolve(reverse("signup")).func.view_class.__module__,
            "arches.app.views.auth",
        )
        self.assertEqual(
            resolve(reverse("confirm_signup")).func.view_class.__module__,
            "arches.app.views.auth",
        )

    def test_login_page_offers_no_signup_link(self):
        response = self.client.get("/en/auth/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Create a new account")


class SignupClosedCheckTests(SimpleTestCase):
    @override_settings(
        ENABLE_USER_SIGNUP=True, SETTINGS_MODULE="manuspectrum.settings_docker"
    )
    def test_error_when_the_production_profile_allows_signup(self):
        messages = check_signup_closed_in_production(None)
        self.assertEqual([m.id for m in messages], ["manuspectrum.E002"])

    @override_settings(
        ENABLE_USER_SIGNUP=False, SETTINGS_MODULE="manuspectrum.settings_docker"
    )
    def test_silent_when_closed(self):
        self.assertEqual(check_signup_closed_in_production(None), [])

    @override_settings(ENABLE_USER_SIGNUP=True, SETTINGS_MODULE="manuspectrum.settings")
    def test_silent_outside_the_production_profile(self):
        self.assertEqual(check_signup_closed_in_production(None), [])
