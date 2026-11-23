"""Invitation, account activation and acceptance of the terms (PP-4, decision 13)."""

import re
import time
from html.parser import HTMLParser
from unittest import mock

import lxml.html
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from manuspectrum.accounts import activation, mailed_links
from manuspectrum.accounts.terms import TERMS_VERSION
from manuspectrum.models import TermsAcceptance
from manuspectrum.password_validation import HasLowerCaseValidator

PASSWORD = "Str0ng!Passphrase-for-tests"
HTML = {"HTTP_ACCEPT": "text/html,application/xhtml+xml"}
IP = "203.0.113.20"


class LowerSubclass(HasLowerCaseValidator):
    pass


def invited(username="newbie", email="newbie@manuspectrum.test"):
    user = User(username=username, email=email)
    user.set_unusable_password()
    user.save()
    return user


def link_path(user):
    return (
        "/en/account/activate/"
        + urlsafe_base64_encode(force_bytes(user.pk))
        + "/"
        + default_token_generator.make_token(user)
    )


def placeholder_path(user):
    return (
        "/en/account/activate/"
        + urlsafe_base64_encode(force_bytes(user.pk))
        + "/set-password"
    )


def browser_origin(response, own="http://testserver"):
    """The `Origin` a browser sends when posting a form from *response*'s page.

    Fetch: a `no-referrer` page posts `Origin: null`; `same-origin` and the
    permissive policies send the page's own origin on a same-origin post.
    """
    policy = response.get("Referrer-Policy", "")
    return "null" if policy == "no-referrer" else own


def browser_post(client, page, path, **data):
    """POST *data* the way a browser does from *page*, CSRF checks enforced."""
    data["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
    return client.post(
        path,
        data,
        HTTP_ORIGIN=browser_origin(page),
        HTTP_X_REAL_IP=IP,
        REMOTE_ADDR="10.0.0.1",
    )


def activate(client, path, **data):
    return client.post(path, data, HTTP_X_REAL_IP=IP, REMOTE_ADDR="10.0.0.1")


REDIRECT_STATUSES = (301, 302, 303, 307, 308)


def is_strict(name, morsel):
    """True for a cookie a browser leaves out of a cross-site request."""
    if morsel["samesite"]:
        return morsel["samesite"].lower() == "strict"
    # `Client.force_login` stores the session cookie without its attributes.
    return (
        name == settings.SESSION_COOKIE_NAME
        and (settings.SESSION_COOKIE_SAMESITE or "").lower() == "strict"
    )


def cross_site_click(client, path):
    """GET *path* as a browser does for a link clicked in a webmail or a mail client.

    The navigation starts on another site, so every request of its redirect
    chain is cross-site: none carries a `SameSite=Strict` cookie, not even one
    set by an earlier response of the same chain. The cookies received are
    kept in *client* (the test client stores them itself); its later requests
    stand for same-site ones and carry them all. Returns the last response of
    the chain.
    """
    while True:
        sent = "; ".join(
            f"{name}={morsel.coded_value}"
            for name, morsel in client.cookies.items()
            if not is_strict(name, morsel)
        )
        response = client.get(path, HTTP_COOKIE=sent, HTTP_SEC_FETCH_SITE="cross-site")
        if response.status_code not in REDIRECT_STATUSES:
            return response
        path = response["Location"]


def head_copies_of(response, token):
    """The attribute values of the page's head that hold *token*."""
    document = lxml.html.fromstring(response.content)
    return document.xpath("//head//@*[contains(., $token)]", token=token)


def open_link(client, path):
    """GET a mailed link, as a browser does: the redirect to the form.

    The cookie it sets stays in *client*, which sends it with later requests.
    """
    response = client.get(path)
    if response.status_code != 302:
        raise AssertionError(f"the link answered {response.status_code}")
    return response


def link_cookies(response, base):
    """The cookies of the flow *base* that *response* sets, by language code."""
    prefix = base + "_"
    return {
        name.removeprefix(prefix): morsel
        for name, morsel in response.cookies.items()
        if name.startswith(prefix)
    }


class MailedLinkCases:
    """What every mailed link does with its token cookie.

    A subclass is a `TestCase` that sets `link` and `form` (the paths in
    English), `fr_link` and `fr_form`, `cookie` (the base name), `folders` (the
    cookie path of each language), `marker` (text only the form holds), and
    defines `client_for(**options)`, `submit(client, page)` (the successful
    form post), `assert_invalid(response)` and `other_cookie` (the base name of
    another flow's cookie).
    """

    def token(self):
        return self.link.rstrip("/").rsplit("/", 1)[1]

    def test_a_valid_link_redirects_to_the_form_and_sets_the_cookie(self):
        client = self.client_for()
        response = client.get(self.link)
        self.assertRedirects(response, self.form, fetch_redirect_response=False)
        self.assertNotIn(self.token(), response["Location"])
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        cookies = link_cookies(response, self.cookie)
        self.assertEqual(set(cookies), {code for code, _ in settings.LANGUAGES})
        for code, morsel in cookies.items():
            self.assertTrue(morsel["httponly"], code)
            self.assertEqual(morsel["samesite"], "Lax", code)
            self.assertEqual(morsel["path"], self.folders[code], code)
            self.assertEqual(morsel["max-age"], 900, code)

    @override_settings(SESSION_COOKIE_SECURE=True)
    def test_the_cookie_is_secure_where_the_session_cookie_is(self):
        response = self.client_for().get(self.link)
        for morsel in link_cookies(response, self.cookie).values():
            self.assertTrue(morsel["secure"])

    def test_a_link_clicked_in_a_webmail_reaches_the_form_in_one_chain(self):
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Strict")
        client = self.client_for(enforce_csrf_checks=True)
        page = cross_site_click(client, self.link)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, self.marker)
        self.assertNotContains(page, self.token())
        self.assertEqual(page["Referrer-Policy"], "same-origin")

    def test_the_form_post_succeeds_and_deletes_the_cookie(self):
        client = self.client_for(enforce_csrf_checks=True)
        page = cross_site_click(client, self.link)
        done = self.submit(client, page)
        cookies = link_cookies(done, self.cookie)
        self.assertEqual(set(cookies), {code for code, _ in settings.LANGUAGES})
        for code, morsel in cookies.items():
            self.assertEqual(morsel["max-age"], 0, code)
            self.assertEqual(morsel["path"], self.folders[code], code)

    def test_a_signed_in_browser_keeps_its_session_after_a_cross_site_click(self):
        client = self.client_for(enforce_csrf_checks=True)
        other = User.objects.create_user("other", "other@manuspectrum.test", PASSWORD)
        client.force_login(other)
        cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        page = cross_site_click(client, self.link)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, self.marker)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, page.cookies)
        self.assertEqual(client.cookies[settings.SESSION_COOKIE_NAME].value, cookie)
        self.assertEqual(client.session["_auth_user_id"], str(other.pk))

    def test_opening_the_link_twice_works_and_consumes_nothing(self):
        client = self.client_for()
        for response in (
            client.get(self.link),
            client.head(self.link),
            client.get(self.link),
        ):
            self.assertEqual(response.status_code, 302)
        self.assertContains(client.get(self.form), self.marker)
        self.assertEqual(self.client_for().get(self.link).status_code, 302)

    def test_a_scanner_that_fetches_the_link_leaves_it_working(self):
        scanner = self.client_for()
        scanner.get(self.link)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, scanner.cookies)
        self.assertEqual(self.client_for().get(self.link).status_code, 302)

    def test_the_form_without_the_cookie_is_invalid_and_deletes_it(self):
        response = self.client_for().get(self.form)
        self.assert_invalid(response)
        cookies = link_cookies(response, self.cookie)
        self.assertEqual(set(cookies), {code for code, _ in settings.LANGUAGES})
        for code, morsel in cookies.items():
            self.assertEqual(morsel["max-age"], 0, code)

    def test_a_tampered_cookie_is_invalid(self):
        client = self.client_for()
        client.cookies[f"{self.cookie}_en"] = "garbage:1a2b:signature"
        response = client.get(self.form)
        self.assert_invalid(response)
        self.assertEqual(link_cookies(response, self.cookie)["en"]["max-age"], 0)

    def test_a_cookie_older_than_fifteen_minutes_is_invalid(self):
        client = self.client_for()
        client.get(self.link)
        self.assertContains(client.get(self.form), self.marker)
        late = time.time() + mailed_links.COOKIE_MAX_AGE + 5
        with mock.patch("django.core.signing.time.time", return_value=late):
            response = client.get(self.form)
        self.assert_invalid(response)
        self.assertEqual(link_cookies(response, self.cookie)["en"]["max-age"], 0)

    def test_a_valid_answer_renews_the_cookie(self):
        client = self.client_for()
        client.get(self.link)
        response = client.get(self.form)
        cookies = link_cookies(response, self.cookie)
        self.assertEqual(set(cookies), {code for code, _ in settings.LANGUAGES})
        for code, morsel in cookies.items():
            self.assertEqual(morsel["max-age"], 900, code)

    def test_the_cookie_of_another_flow_does_not_unlock_the_form(self):
        client = self.client_for()
        opened = client.get(self.link)
        client.cookies.pop(f"{self.cookie}_en")
        client.cookies[f"{self.other_cookie}_en"] = opened.cookies[
            f"{self.cookie}_en"
        ].value
        self.assert_invalid(client.get(self.form))

    def test_the_cookie_of_another_language_does_not_unlock_the_form(self):
        client = self.client_for()
        client.get(self.link)
        client.cookies.pop(f"{self.cookie}_en")
        self.assert_invalid(client.get(self.form))

    def test_a_spent_link_is_invalid_when_opened_again(self):
        client = self.client_for(enforce_csrf_checks=True)
        page = cross_site_click(client, self.link)
        self.submit(client, page)
        self.assert_invalid(self.client_for().get(self.link))

    def test_a_refused_link_page_holds_no_copy_of_its_token_in_its_head(self):
        client = self.client_for(enforce_csrf_checks=True)
        self.submit(client, cross_site_click(client, self.link))
        response = self.client_for().get(self.link)
        self.assert_invalid(response)
        self.assertEqual(head_copies_of(response, self.token()), [])

    def test_a_post_on_the_link_is_not_allowed(self):
        response = self.client_for().post(self.link)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(link_cookies(response, self.cookie), {})

    def test_other_methods_on_the_link_are_not_allowed(self):
        self.assertEqual(self.client_for().put(self.link).status_code, 405)

    def test_the_form_post_without_the_csrf_token_is_refused(self):
        client = self.client_for(enforce_csrf_checks=True)
        client.get(self.link)
        response = client.post(self.form, HTTP_ORIGIN="http://testserver")
        self.assertEqual(response.status_code, 403)

    def test_a_french_link_opens_the_form_in_french(self):
        client = self.client_for()
        response = client.get(self.fr_link)
        self.assertRedirects(response, self.fr_form, fetch_redirect_response=False)
        self.assertContains(client.get(self.fr_form), self.marker)

    def test_the_language_switch_keeps_the_form_working(self):
        client = self.client_for()
        client.get(self.fr_link)
        self.assertContains(client.get(self.fr_form), self.marker)
        self.assertContains(client.get(self.form), self.marker)


class ExpiredStepCases:
    """The page a form answers when its cookie is gone while the link still works.

    Needs `MailedLinkCases` and `assert_invalid` from the same class.
    """

    def assert_expired(self, response, heading="This page has expired"):
        self.assert_invalid(response)
        self.assertContains(response, heading, status_code=410)
        self.assertNotContains(response, "This link is not valid", status_code=410)
        cookies = link_cookies(response, self.cookie)
        self.assertEqual(set(cookies), {code for code, _ in settings.LANGUAGES})
        for code, morsel in cookies.items():
            self.assertEqual(morsel["max-age"], 0, code)

    def test_the_form_without_the_cookie_says_the_page_expired(self):
        response = self.client_for().get(self.form)
        self.assert_expired(response)
        self.assertContains(response, "stays open for 15 minutes", status_code=410)

    def test_the_expired_page_is_in_french_under_fr(self):
        response = self.client_for().get(self.fr_form)
        self.assert_expired(response, "Cette page a expiré")
        self.assertContains(response, "reste ouverte 15 minutes", status_code=410)

    def test_a_cookie_older_than_fifteen_minutes_says_the_page_expired(self):
        client = self.client_for()
        client.get(self.link)
        late = time.time() + mailed_links.COOKIE_MAX_AGE + 5
        with mock.patch("django.core.signing.time.time", return_value=late):
            response = client.get(self.form)
        self.assert_expired(response)

    def test_a_refused_token_with_its_cookie_shows_the_invalid_page(self):
        client = self.client_for()
        client.get(self.link)
        other = self.client_for(enforce_csrf_checks=True)
        self.submit(other, cross_site_click(other, self.link))
        response = client.get(self.form)
        self.assert_invalid(response)
        self.assertContains(response, "This link is not valid", status_code=410)
        self.assertNotContains(response, "This page has expired", status_code=410)


class _ParagraphNesting(HTMLParser):
    """Collect the block elements that a browser would pull out of an open `<p>`."""

    BLOCKS = {"details", "div", "ul", "ol", "table", "form", "p"}

    def __init__(self):
        super().__init__()
        self.open_p = 0
        self.offenders = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCKS and self.open_p:
            self.offenders.append(tag)
        if tag == "p":
            self.open_p += 1

    def handle_endtag(self, tag):
        if tag == "p" and self.open_p:
            self.open_p -= 1


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client(raise_request_exception=False)


class InvitationTests(Base):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_superuser(
            "boss", "boss@manuspectrum.test", PASSWORD
        )
        self.client.force_login(self.staff)

    def run_action(self, *users):
        return self.client.post(
            reverse("admin:auth_user_changelist"),
            {
                "action": "send_invitation",
                "_selected_action": [u.pk for u in users],
            },
            follow=True,
        )

    def test_one_mail_english_then_french_with_a_working_link(self):
        user = invited()
        self.run_action(user)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertTrue(message.subject.startswith("[ManuSpectrum][Account] "))
        self.assertEqual(message.extra_headers["X-ManuSpectrum-Category"], "Account")
        self.assertEqual(message.to, ["newbie@manuspectrum.test"])
        body = message.body
        self.assertLess(
            body.index("Activate my account"), body.index("Activer mon compte")
        )
        path = re.search(r"https?://[^\s]+/account/activate/[^\s]+", body).group(0)
        path = "/" + path.split("/", 3)[3]
        response = cross_site_click(self.client, path)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="accept_terms"')

    def test_each_language_part_links_its_own_language_with_one_token(self):
        user = invited()
        self.run_action(user)
        text_en, text_fr = mail.outbox[0].body.split("-" * 40)
        pattern = r"/(en|fr)/account/activate/([^\s/]+)/([^\s/]+)"
        en = re.search(pattern, text_en)
        fr = re.search(pattern, text_fr)
        self.assertEqual((en.group(1), fr.group(1)), ("en", "fr"))
        self.assertEqual(en.group(2, 3), fr.group(2, 3))
        self.assertFalse(re.search(r"/fr/account/activate/", text_en))

    def test_refused_for_a_usable_password_or_no_address(self):
        has_password = User.objects.create_user("p", "p@manuspectrum.test", PASSWORD)
        no_mail = invited("nomail", "")
        self.run_action(has_password, no_mail)
        self.assertEqual(len(mail.outbox), 0)
        with self.assertRaises(ValueError):
            activation.send_invitation(has_password)

    def test_the_user_admin_keeps_its_own_class_and_gains_the_action(self):
        model_admin = admin.site._registry[User]
        self.assertIn("send_invitation", model_admin.actions)


class ActivationTests(Base):
    def setUp(self):
        super().setUp()
        self.user = invited()
        self.link = link_path(self.user)
        self.path = placeholder_path(self.user)
        open_link(self.client, self.link)

    def good(self, **overrides):
        data = {
            "new_password1": PASSWORD,
            "new_password2": PASSWORD,
            "accept_terms": "on",
        }
        data.update(overrides)
        return {k: v for k, v in data.items() if v is not None}

    def test_the_page_carries_the_rules_the_server_enforces(self):
        html = self.client.get(self.path).content.decode()
        self.assertIn('data-min-length="12"', html)
        for rule in ("length", "upper", "lower", "digit", "symbol"):
            self.assertIn(f'data-rule="{rule}"', html)
        self.assertIn("data-ms-pw-match", html)
        self.assertEqual(html.count("data-ms-pw-wrap"), 2)

    def test_the_minimum_length_follows_the_settings(self):
        validators = [
            {
                "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
                "OPTIONS": {"min_length": 20},
            }
        ]
        with override_settings(AUTH_PASSWORD_VALIDATORS=validators):
            html = self.client.get(self.path).content.decode()
        self.assertIn('data-min-length="20"', html)
        self.assertNotIn('data-rule="upper"', html)
        self.assertNotIn('data-rule="symbol"', html)

    def info_items(self, html):
        block = re.search(r'<ul class="ms-pw-info__list"[^>]*>(.*?)</ul>', html, re.S)
        self.assertIsNotNone(block)
        return re.findall(r"<li>(.*?)</li>", block.group(1))

    def test_the_raw_validator_help_list_is_not_rendered(self):
        html = self.client.get(self.path).content.decode()
        self.assertNotIn("ms-form-help", html)
        self.assertNotIn("Be longer than", html)

    def test_the_info_lists_each_configured_rule_once(self):
        html = self.client.get(self.path).content.decode()
        self.assertIn('<summary aria-label="Password rules">', html)
        self.assertEqual(
            self.info_items(html),
            [
                "At least 12 characters",
                "One upper-case letter",
                "One lower-case letter",
                "One digit",
                "One symbol",
                "Not a commonly used password",
                "Not too close to your name, username or e-mail address",
            ],
        )
        self.assertEqual(html.count("ms-pw-info__list"), 1)

    def test_the_info_is_in_french_under_fr(self):
        html = self.client.get("/fr" + self.path.removeprefix("/en")).content.decode()
        self.assertIn('aria-label="Règles du mot de passe"', html)
        items = self.info_items(html)
        self.assertIn("Au moins 12 caractères", items)
        self.assertIn("Un symbole", items)
        self.assertEqual(len(items), len(set(items)))
        self.assertFalse([i for i in items if i.startswith("Not ")])

    def test_an_unconfigured_validator_has_no_rule_and_no_note(self):
        validators = [
            {
                "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
                "OPTIONS": {"min_length": 20},
            }
        ]
        with override_settings(AUTH_PASSWORD_VALIDATORS=validators):
            html = self.client.get(self.path).content.decode()
        self.assertEqual(self.info_items(html), ["At least 20 characters"])
        self.assertNotIn("ms-pw-note", html)

    def test_no_block_element_sits_inside_a_paragraph(self):
        html = self.client.get(self.path).content.decode()
        parser = _ParagraphNesting()
        parser.feed(html)
        self.assertEqual(parser.offenders, [])

    def page_tree(self):
        return lxml.html.fromstring(self.client.get(self.path).content)

    def test_the_lists_sit_in_the_meter_and_the_field_wrapper(self):
        tree = self.page_tree()
        fields = tree.xpath('//*[contains(concat(" ", @class, " "), " ms-pw-field ")]')
        self.assertEqual({field.tag for field in fields}, {"div"})
        self.assertTrue(
            fields[0].xpath(
                './/details[contains(@class, "ms-pw-info")]'
                '//ul[contains(@class, "ms-pw-info__list")]'
            )
        )
        (meter,) = tree.xpath("//*[@data-ms-pw-meter]")
        self.assertIn("hidden", meter.attrib)
        self.assertTrue(meter.xpath('.//ul[contains(@class, "ms-pw-rules")]'))
        self.assertEqual(tree.xpath("//p//ul | //p//details | //p//div"), [])

    def test_the_match_line_names_the_first_field_by_its_id(self):
        tree = self.page_tree()
        (first,) = tree.xpath('//input[@name="new_password1"]')
        (line,) = tree.xpath("//*[@data-ms-pw-match]")
        self.assertEqual(line.get("data-with"), first.get("id"))

    def test_the_first_field_is_described_by_the_rules_and_the_meter_word(self):
        tree = self.page_tree()
        (first,) = tree.xpath('//input[@name="new_password1"]')
        ids = first.get("aria-describedby").split()
        self.assertEqual(ids, [f"{first.get('id')}-rules", f"{first.get('id')}-word"])
        (rules,) = tree.xpath('//ul[contains(@class, "ms-pw-rules")]')
        (word,) = tree.xpath("//*[@data-ms-pw-word]")
        self.assertEqual([rules.get("id"), word.get("id")], ids)

    def test_without_a_meter_the_first_field_is_described_by_the_rule_list(self):
        validators = [
            {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"}
        ]
        with override_settings(AUTH_PASSWORD_VALIDATORS=validators):
            tree = lxml.html.fromstring(self.client.get(self.path).content)
        (first,) = tree.xpath('//input[@name="new_password1"]')
        (info,) = tree.xpath('//ul[contains(@class, "ms-pw-info__list")]')
        self.assertEqual(first.get("aria-describedby"), info.get("id"))

    def test_without_a_checkable_rule_there_is_no_meter(self):
        validators = [
            {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
            {
                "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
            },
        ]
        with override_settings(AUTH_PASSWORD_VALIDATORS=validators):
            html = self.client.get(self.path).content.decode()
        self.assertNotIn("data-ms-pw-meter", html)
        self.assertIn("ms-pw-info__list", html)

    def test_a_subclass_of_the_lower_case_validator_is_detected(self):
        from manuspectrum.accounts.password_rules import password_rules

        validators = [{"NAME": "tests.test_accounts_activation.LowerSubclass"}]
        with override_settings(AUTH_PASSWORD_VALIDATORS=validators):
            self.assertTrue(password_rules()["lower"])

    def test_the_numeric_rule_is_listed_only_without_a_case_rule(self):
        numeric = {
            "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"
        }
        with override_settings(AUTH_PASSWORD_VALIDATORS=[numeric]):
            html = self.client.get(self.path).content.decode()
        self.assertEqual(self.info_items(html), ["Not only digits"])

    def test_the_static_note_follows_the_common_and_similarity_validators(self):
        html = self.client.get(self.path).content.decode()
        self.assertEqual(html.count("ms-pw-note"), 1)

    def test_a_bad_token_is_refused_without_a_form(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        response = self.client.get(f"/en/account/activate/{uid}/bad-token")
        self.assertEqual(response.status_code, 410)
        self.assertNotContains(response, "<form", status_code=410)

    def test_an_unknown_user_is_refused(self):
        response = self.client.get("/en/account/activate/zzzz/abc-def")
        self.assertEqual(response.status_code, 410)

    def test_an_expired_token_is_refused(self):
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            response = Client().get(self.link)
            expired = self.client.get(self.path)
        self.assertEqual(response.status_code, 410)
        self.assertEqual(expired.status_code, 410)

    def test_a_no_referrer_page_would_post_a_null_origin_that_csrf_refuses(self):
        client = Client(enforce_csrf_checks=True)
        page = cross_site_click(client, self.link)
        page["Referrer-Policy"] = "no-referrer"
        response = browser_post(client, page, self.path, **self.good())
        self.assertEqual(response.status_code, 403)

    def test_the_token_less_page_needs_the_cookie(self):
        for client in (Client(), Client(raise_request_exception=False)):
            response = client.get(self.path)
            self.assertEqual(response.status_code, 410)
            self.assertEqual(response["Referrer-Policy"], "same-origin")
            self.assertNotContains(response, "<form", status_code=410)
            self.assertEqual(
                activate(client, self.path, **self.good()).status_code, 410
            )
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())

    def test_the_terms_and_the_version_are_shown(self):
        response = self.client.get(self.path)
        self.assertContains(response, TERMS_VERSION)
        self.assertContains(response, 'name="accept_terms"')
        self.assertContains(response, "not a data repository")

    def test_no_checkbox_refuses_and_stores_nothing(self):
        response = activate(self.client, self.path, **self.good(accept_terms=None))
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        self.assertFalse(TermsAcceptance.objects.exists())

    def test_a_weak_password_is_refused(self):
        response = activate(
            self.client,
            self.path,
            **self.good(new_password1="1234", new_password2="1234"),
        )
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        self.assertFalse(TermsAcceptance.objects.exists())

    def test_success_sets_the_password_records_logs_in_and_kills_the_link(self):
        response = activate(self.client, self.path, **self.good())
        self.assertRedirects(
            response, "/en/account/two-factor", fetch_redirect_response=False
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertTrue(
            TermsAcceptance.objects.filter(
                user=self.user, version=TERMS_VERSION
            ).exists()
        )
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))
        self.assertEqual(Client().get(self.link).status_code, 410)
        self.assertEqual(self.client.get(self.path).status_code, 410)

    def test_the_post_is_rate_limited(self):
        with mock.patch("django_ratelimit.core._get_window", return_value=1_000_000):
            statuses = [
                activate(
                    self.client, self.path, **self.good(accept_terms=None)
                ).status_code
                for _ in range(7)
            ]
        self.assertIn(429, statuses)


class LinkLandingTests(MailedLinkCases, ExpiredStepCases, Base):
    """The activation link: a cookie, a redirect, then the form."""

    cookie = "ms_activation_link"
    other_cookie = "ms_reset_link"
    marker = 'name="accept_terms"'

    def setUp(self):
        super().setUp()
        self.user = invited()
        self.link = link_path(self.user)
        self.form = self.path = placeholder_path(self.user)
        self.fr_link = "/fr" + self.link.removeprefix("/en")
        self.fr_form = "/fr" + self.form.removeprefix("/en")
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.folders = {
            code: f"/{code}/account/activate/{uid}/" for code, _ in settings.LANGUAGES
        }

    def client_for(self, **options):
        return Client(**options)

    def good(self):
        return {
            "new_password1": PASSWORD,
            "new_password2": PASSWORD,
            "accept_terms": "on",
        }

    def submit(self, client, page):
        done = browser_post(client, page, self.form, **self.good())
        self.assertRedirects(
            done, "/en/account/two-factor", fetch_redirect_response=False
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        return done

    def assert_invalid(self, response):
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertNotContains(response, "accept_terms", status_code=410)

    def test_the_form_is_in_french_under_fr(self):
        client = Client()
        client.get(self.fr_link)
        self.assertContains(client.get(self.fr_form), "Activer mon compte")

    def test_the_form_page_holds_no_token_and_no_copy_of_its_url_in_its_head(self):
        client = Client()
        client.get(self.link)
        page = client.get(self.form)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '<meta name="robots" content="noindex')
        self.assertNotContains(page, self.token())
        document = lxml.html.fromstring(page.content)
        self.assertEqual(
            document.xpath('//link[@rel="canonical" or @rel="alternate"]'), []
        )
        self.assertEqual(document.xpath('//meta[@property="og:url"]'), [])
        (form,) = document.xpath('//form[@method="post"]')
        self.assertIsNone(form.get("action"))

    def test_a_refused_post_keeps_the_form_and_renews_the_cookie(self):
        client = Client()
        client.get(self.link)
        response = client.post(
            self.form, {"new_password1": PASSWORD, "new_password2": PASSWORD}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            link_cookies(response, self.cookie)["en"]["max-age"],
            mailed_links.COOKIE_MAX_AGE,
        )

    def test_a_bad_link_is_refused_and_sets_no_cookie(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        response = Client().get(f"/en/account/activate/{uid}/bad-token")
        self.assertEqual(response.status_code, 410)
        self.assertEqual(
            {
                name: morsel
                for name, morsel in link_cookies(response, self.cookie).items()
                if morsel["max-age"] != 0
            },
            {},
        )

    def test_a_link_cannot_add_attributes_to_the_cookie_header(self):
        response = Client().get("/en/account/activate/x%3BDomain=evil.test%2C/bad")
        self.assertEqual(response.status_code, 410)
        header = response.cookies[f"{self.cookie}_en"].output()
        self.assertIn("Path=/en/account/activate/x%3BDomain%3Devil.test%2C/", header)
        self.assertNotIn("Domain=evil", header)


class MiddlewareTests(Base):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user("mia", "mia@manuspectrum.test", PASSWORD)
        self.client.force_login(self.user)

    def accept(self):
        TermsAcceptance.objects.create(user=self.user, version=TERMS_VERSION)

    def test_a_page_navigation_is_redirected_to_the_accept_page(self):
        response = self.client.get("/en/about/team", **HTML)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/en/account/terms?next=/en/about/team")

    def test_requests_that_are_not_navigations_are_left_alone(self):
        self.assertNotEqual(self.client.get("/en/about/team").status_code, 302)
        self.assertNotEqual(
            self.client.get(
                "/en/about/team",
                HTTP_ACCEPT="text/html",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            ).status_code,
            302,
        )
        self.assertNotEqual(
            self.client.get(
                "/en/api/model-graph", HTTP_ACCEPT="application/json"
            ).status_code,
            302,
        )
        self.assertNotEqual(
            self.client.get("/en/api/model-graph", **HTML).status_code, 302
        )
        self.assertNotEqual(self.client.post("/en/about/team", **HTML).status_code, 302)
        self.assertNotEqual(self.client.get("/static/x.css", **HTML).status_code, 302)

    def test_the_exempt_pages_are_reachable(self):
        for path in (
            "/en/account/terms",
            "/en/account/two-factor",
            "/en/auth/?logout=true",
        ):
            response = self.client.get(path, **HTML)
            self.assertFalse(
                response.status_code == 302
                and response["Location"].startswith("/en/account/terms"),
                path,
            )

    def test_anonymous_visitors_are_untouched(self):
        response = Client().get("/en/about/team", **HTML)
        self.assertEqual(response.status_code, 200)

    def test_accepting_records_and_returns_to_next(self):
        response = self.client.post(
            "/en/account/terms", {"accept_terms": "on", "next": "/en/about/team"}
        )
        self.assertRedirects(response, "/en/about/team", fetch_redirect_response=False)
        self.assertTrue(
            TermsAcceptance.objects.filter(
                user=self.user, version=TERMS_VERSION
            ).exists()
        )
        self.assertEqual(self.client.get("/en/about/team", **HTML).status_code, 200)

    def test_accepting_without_the_box_is_refused(self):
        response = self.client.post("/en/account/terms", {"next": "/en/about/team"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(TermsAcceptance.objects.exists())

    def test_an_external_next_is_refused(self):
        for target in ("https://evil.example/x", "//evil.example/x"):
            response = self.client.post(
                "/en/account/terms", {"accept_terms": "on", "next": target}
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], reverse("root"))

    def test_a_new_version_asks_again(self):
        self.accept()
        self.assertEqual(self.client.get("/en/about/team", **HTML).status_code, 200)
        with mock.patch.object(activation, "TERMS_VERSION", "2099-01-01"):
            response = self.client.get("/en/about/team", **HTML)
        self.assertEqual(response.status_code, 302)

    def test_a_signed_out_visitor_is_sent_to_sign_in_from_the_accept_page(self):
        response = Client().get("/en/account/terms")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/en/auth/"))


class PasswordRulesConfigTests(TestCase):
    def test_an_unknown_validator_is_skipped(self):
        from manuspectrum.accounts.password_rules import password_rules

        validators = [
            {"NAME": "no.such.module.Validator"},
            {
                "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
                "OPTIONS": {"min_length": 14},
            },
        ]
        with override_settings(AUTH_PASSWORD_VALIDATORS=validators):
            rules = password_rules()
        self.assertEqual(rules["min_length"], 14)
