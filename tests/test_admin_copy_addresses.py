"""The superuser action « Copy the e-mail addresses » on the User admin.

Usage:
    python manage.py test tests.test_admin_copy_addresses --settings="tests.test_settings" --noinput
"""

from datetime import date

from django.contrib.auth.models import Permission, User
from django.contrib.staticfiles import finders
from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse

from manuspectrum.accounts import retention
from manuspectrum.models import AccountRetention

PASSWORD = "Str0ng!Passphrase-for-tests"


def make(username, email, **extra):
    return User.objects.create_user(username, email, PASSWORD, **extra)


class CopyAddressesTests(TestCase):
    def setUp(self):
        self.client = Client(raise_request_exception=False)
        self.boss = User.objects.create_superuser(
            "boss", "boss@manuspectrum.test", PASSWORD
        )

    def run_action(self, client, *users):
        return client.post(
            reverse("admin:auth_user_changelist"),
            {"action": "copy_addresses", "_selected_action": [u.pk for u in users]},
        )

    def test_lists_the_reachable_addresses_sorted_and_merged(self):
        anon = User.objects.get(username="anonymous")
        User.objects.filter(pk=anon.pk).update(email="anon@manuspectrum.test")
        users = [
            make("b", "Zed@manuspectrum.test"),
            make("a", "amy@manuspectrum.test"),
            make("dup", "AMY@manuspectrum.test"),
            make("off", "off@manuspectrum.test", is_active=False),
            make("blank", ""),
            anon,
        ]
        gone = make("gone", "gone@manuspectrum.test")
        AccountRetention.objects.create(user_id=gone.pk, anonymised_on=date(2026, 1, 1))
        renamed = make("temp", "renamed@manuspectrum.test")
        User.objects.filter(pk=renamed.pk).update(
            username=retention.former_username(renamed.pk)
        )
        self.client.force_login(self.boss)
        response = self.run_action(self.client, *users, gone, renamed)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["addresses_text"],
            "amy@manuspectrum.test, Zed@manuspectrum.test",
        )
        reached = response.context["audience"]
        self.assertEqual(
            (reached.inactive, reached.no_address, reached.anonymised),
            (1, 1, 2),
        )
        self.assertContains(response, "never in To or Cc")
        self.assertNotContains(response, "off@manuspectrum.test")
        self.assertNotContains(response, "anon@manuspectrum.test")
        self.assertNotContains(response, "gone@manuspectrum.test")
        self.assertNotContains(response, "renamed@manuspectrum.test")

    def test_merged_duplicates_are_counted_on_the_page(self):
        users = [
            make("a", "amy@manuspectrum.test"),
            make("b", "AMY@manuspectrum.test"),
            make("c", "Amy@manuspectrum.test"),
        ]
        self.client.force_login(self.boss)
        response = self.run_action(self.client, *users)
        self.assertContains(response, "2 duplicate addresses were merged.")
        one = self.run_action(self.client, *users[:2])
        self.assertContains(one, "1 duplicate address was merged.")

    def test_no_duplicate_line_without_duplicates(self):
        user = make("a", "amy@manuspectrum.test")
        self.client.force_login(self.boss)
        response = self.run_action(self.client, user)
        self.assertNotContains(response, "duplicate")

    def test_the_copy_box_is_driven_by_the_shared_script(self):
        user = make("a", "amy@manuspectrum.test")
        self.client.force_login(self.boss)
        response = self.run_action(self.client, user)
        self.assertContains(response, "js/standalone/copy-text.js")
        self.assertContains(response, 'data-ms-copy data-ms-copy-source="textarea"')
        self.assertContains(response, "data-ms-copy-button")
        self.assertContains(response, "data-ms-copy-status")

    def test_the_shared_copy_script_is_found_by_staticfiles(self):
        self.assertIsNotNone(finders.find("js/standalone/copy-text.js"))
        self.assertIsNone(finders.find("js/accounts/copy-key.js"))
        self.assertIsNone(finders.find("js/admin/copy-addresses.js"))

    def test_the_page_sends_nothing_and_links_no_mailto(self):
        user = make("u", "u@manuspectrum.test")
        self.client.force_login(self.boss)
        response = self.run_action(self.client, user)
        self.assertNotContains(response, "mailto:")
        self.assertEqual(mail.outbox, [])

    def test_staff_without_superuser_cannot_run_it(self):
        staff = make("staff", "staff@manuspectrum.test", is_staff=True)
        staff.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="auth", content_type__model="user"
            )
        )
        target = make("t", "t@manuspectrum.test")
        self.client.force_login(staff)
        listing = self.client.get(reverse("admin:auth_user_changelist"))
        self.assertNotContains(listing, "copy_addresses")
        response = self.run_action(self.client, target)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(getattr(response, "context_data", None))


class CopyAddressesGuardTests(TestCase):
    def test_the_action_refuses_a_staff_member_who_is_not_superuser(self):
        from unittest import mock

        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        staff = User.objects.create_user(
            "staff-only", "staff@example.org", is_staff=True
        )
        request = RequestFactory().post("/en/admin/auth/user/")
        request.user = staff
        model_admin = django_admin.site._registry[User]
        with mock.patch.object(model_admin, "message_user") as told:
            result = model_admin.copy_addresses(request, User.objects.all())
        self.assertIsNone(result)
        told.assert_called_once()
