"""Embargo and cleanup records and their Django admin (PP-4, T5)."""

import uuid
from datetime import date, datetime, timedelta
from unittest import mock

from arches.app.models.models import GraphModel, ResourceInstance
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from manuspectrum.models import Embargo, EmbargoEvent, WorkflowCleanup
from manuspectrum.observability import activity

PASSWORD = "Str0ng!Passphrase-for-tests"
TODAY = date(2026, 10, 12)
LIST_URL = "/en/admin/manuspectrum/embargo/"


def change_url(embargo):
    return f"{LIST_URL}{embargo.pk}/change/"


class EmbargoTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.graph = GraphModel.objects.create(
            name="embargo_model", isresource=True, is_active=True, slug="emb_model"
        )
        cls.root = User.objects.create_superuser(
            "root", "r@manuspectrum.test", PASSWORD
        )
        cls.admin_user = User.objects.create_user(
            "admin_user", "a@manuspectrum.test", PASSWORD, is_staff=True
        )
        cls.admin_user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="manuspectrum",
                content_type__model__in=("embargo", "embargoevent"),
            )
        )
        cls.editor = User.objects.create_user(
            "editor", "e@manuspectrum.test", PASSWORD, is_staff=True
        )

    def make(self, ends_on=None, created=None):
        resource = ResourceInstance.objects.create(
            graph=self.graph,
            descriptors={"en": {"name": "Codex X"}},
        )
        embargo = Embargo.objects.create(resourceinstance=resource, ends_on=ends_on)
        if created:
            Embargo.objects.filter(pk=embargo.pk).update(created=created)
            embargo.refresh_from_db()
        return embargo

    def save_end(self, user, embargo, ends_on):
        return self.client_for(user).post(
            change_url(embargo),
            {
                "ends_on": ends_on.isoformat(),
                "events-TOTAL_FORMS": 0,
                "events-INITIAL_FORMS": 0,
            },
        )

    def client_for(self, user):
        client = Client(raise_request_exception=False)
        client.force_login(user)
        return client


class ValidationTests(EmbargoTestCase):
    def test_a_past_date_is_refused(self):
        embargo = self.make()
        with self.assertRaises(ValidationError):
            embargo.validate_end(TODAY, superuser=True, today=TODAY)

    def test_no_end_date_is_accepted(self):
        self.make().validate_end(None, today=TODAY)

    def test_one_year_from_the_start_is_accepted(self):
        embargo = self.make(created=datetime(2026, 10, 12, 8))
        embargo.validate_end(date(2027, 10, 12), today=TODAY)

    def test_beyond_one_year_is_refused_for_an_administrator(self):
        embargo = self.make(created=datetime(2026, 10, 12, 8))
        with self.assertRaises(ValidationError):
            embargo.validate_end(date(2027, 10, 13), today=TODAY)

    def test_a_superuser_may_go_beyond_one_year(self):
        embargo = self.make(created=datetime(2026, 10, 12, 8))
        embargo.validate_end(date(2028, 1, 1), superuser=True, today=TODAY)

    def test_the_maximum_comes_from_the_setting(self):
        embargo = self.make(created=datetime(2026, 10, 12, 8))
        with override_settings(EMBARGO_MAX_MONTHS=3):
            with self.assertRaises(ValidationError):
                embargo.validate_end(date(2027, 1, 13), today=TODAY)
            embargo.validate_end(date(2027, 1, 12), today=TODAY)


class ChangeEndTests(EmbargoTestCase):
    def test_extending_records_who_when_old_and_new(self):
        embargo = self.make(ends_on=date(2026, 12, 1))
        embargo.notices_sent = ["d30"]
        embargo.save()
        embargo.change_end(date(2027, 3, 1), self.admin_user)
        event = embargo.events.get()
        self.assertEqual(
            (event.kind, event.by, event.from_date, event.to_date),
            (
                EmbargoEvent.EXTENDED,
                self.admin_user,
                date(2026, 12, 1),
                date(2027, 3, 1),
            ),
        )
        self.assertIsNotNone(event.at)
        embargo.refresh_from_db()
        self.assertEqual(embargo.notices_sent, [])

    def test_dating_an_undated_restriction_is_a_dated_event(self):
        embargo = self.make()
        embargo.change_end(date(2027, 1, 1), self.admin_user)
        self.assertEqual(embargo.events.get().kind, EmbargoEvent.DATED)

    def test_an_unchanged_date_writes_nothing(self):
        embargo = self.make(ends_on=date(2027, 1, 1))
        self.assertIsNone(embargo.change_end(date(2027, 1, 1), self.admin_user))
        self.assertEqual(embargo.events.count(), 0)

    def test_a_lifted_embargo_refuses_a_new_end_even_from_a_stale_instance(self):
        embargo = self.make(ends_on=date.today() + timedelta(days=10))
        Embargo.objects.filter(pk=embargo.pk).update(state=Embargo.LIFTED)
        with self.assertRaises(ValidationError):
            embargo.change_end(date.today() + timedelta(days=60), self.admin_user)
        self.assertEqual(embargo.events.count(), 0)
        embargo.refresh_from_db()
        self.assertEqual(embargo.ends_on, date.today() + timedelta(days=10))

    def test_the_change_runs_under_a_row_lock(self):
        embargo = self.make(ends_on=date.today() + timedelta(days=10))
        with CaptureQueriesContext(connection) as queries:
            embargo.change_end(date.today() + timedelta(days=20), self.admin_user)
        self.assertTrue(any("FOR UPDATE" in q["sql"] for q in queries))


class AdminTests(EmbargoTestCase):
    def test_only_a_superuser_can_remove_an_end_date(self):
        end = date.today() + timedelta(days=10)
        embargo = self.make(ends_on=end)
        post = lambda user: self.client_for(user).post(
            change_url(embargo),
            {"ends_on": "", "events-TOTAL_FORMS": 0, "events-INITIAL_FORMS": 0},
        )
        response = post(self.admin_user)
        self.assertEqual(response.status_code, 200)
        self.assertIn("ends_on", response.context["adminform"].form.errors)
        embargo.refresh_from_db()
        self.assertEqual(embargo.ends_on, end)
        self.assertEqual(post(self.root).status_code, 302)
        embargo.refresh_from_db()
        self.assertIsNone(embargo.ends_on)
        self.assertEqual(embargo.events.get().kind, EmbargoEvent.UNDATED)

    def test_a_lifted_or_released_embargo_cannot_get_a_new_end(self):
        for state in (Embargo.LIFTED, Embargo.RELEASED):
            embargo = self.make(ends_on=date.today() + timedelta(days=10))
            Embargo.objects.filter(pk=embargo.pk).update(state=state)
            response = self.save_end(
                self.admin_user, embargo, date.today() + timedelta(days=60)
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("ends_on", response.context["adminform"].form.errors)
            embargo.refresh_from_db()
            self.assertEqual(embargo.ends_on, date.today() + timedelta(days=10))
            self.assertEqual(embargo.events.count(), 0)

    def test_the_extend_action_leaves_a_lifted_embargo_alone(self):
        embargo = self.make(ends_on=date.today() + timedelta(days=30))
        Embargo.objects.filter(pk=embargo.pk).update(state=Embargo.LIFTED)
        self.client_for(self.admin_user).post(
            LIST_URL, {"action": "extend_3", "_selected_action": [embargo.pk]}
        )
        self.assertEqual(embargo.events.count(), 0)

    def test_the_change_list_loads_for_a_permitted_user(self):
        self.make(ends_on=date(2027, 1, 1))
        response = self.client_for(self.admin_user).get(LIST_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Codex X")

    def test_the_change_list_is_refused_to_an_editor_without_the_permission(self):
        response = self.client_for(self.editor).get(LIST_URL)
        self.assertEqual(response.status_code, 403)

    def test_saving_a_new_date_writes_an_event_and_clears_notices(self):
        embargo = self.make(ends_on=date.today() + timedelta(days=10))
        embargo.notices_sent = ["d30"]
        embargo.save()
        new_end = date.today() + timedelta(days=60)
        response = self.save_end(self.admin_user, embargo, new_end)
        self.assertEqual(response.status_code, 302)
        embargo.refresh_from_db()
        self.assertEqual(embargo.ends_on, new_end)
        self.assertEqual(embargo.notices_sent, [])
        event = embargo.events.get()
        self.assertEqual(
            (event.kind, event.by), (EmbargoEvent.EXTENDED, self.admin_user)
        )

    def test_a_past_date_is_refused_by_the_form(self):
        embargo = self.make(ends_on=date.today() + timedelta(days=10))
        response = self.save_end(self.admin_user, embargo, date.today())
        self.assertEqual(response.status_code, 200)
        self.assertIn("ends_on", response.context["adminform"].form.errors)
        embargo.refresh_from_db()
        self.assertEqual(embargo.ends_on, date.today() + timedelta(days=10))
        self.assertEqual(embargo.events.count(), 0)

    def test_a_save_refused_by_the_model_shows_only_the_error_and_writes_no_log(self):
        embargo = self.make(ends_on=date.today() + timedelta(days=10))
        client = self.client_for(self.admin_user)
        new_end = date.today() + timedelta(days=60)
        with mock.patch.object(
            Embargo,
            "change_end",
            side_effect=ValidationError(
                "Only an active embargo can change its end date."
            ),
        ):
            response = client.post(
                change_url(embargo),
                {
                    "ends_on": new_end.isoformat(),
                    "events-TOTAL_FORMS": 0,
                    "events-INITIAL_FORMS": 0,
                },
                follow=True,
            )
        texts = [(m.level, str(m)) for m in response.context["messages"]]
        self.assertEqual(
            texts,
            [(40, "Only an active embargo can change its end date.")],
        )
        self.assertFalse(LogEntry.objects.filter(object_id=str(embargo.pk)).exists())
        embargo.refresh_from_db()
        self.assertEqual(embargo.ends_on, date.today() + timedelta(days=10))

    def test_a_date_beyond_the_maximum_is_refused_to_an_administrator(self):
        embargo = self.make()
        far = date.today() + timedelta(days=400)
        response = self.save_end(self.admin_user, embargo, far)
        self.assertEqual(response.status_code, 200)
        self.assertIn("ends_on", response.context["adminform"].form.errors)
        embargo.refresh_from_db()
        self.assertIsNone(embargo.ends_on)

    def test_a_superuser_may_set_a_date_beyond_the_maximum(self):
        embargo = self.make()
        far = date.today() + timedelta(days=400)
        self.save_end(self.root, embargo, far)
        embargo.refresh_from_db()
        self.assertEqual(embargo.ends_on, far)

    def test_the_resource_and_the_state_cannot_be_edited(self):
        embargo = self.make(ends_on=date.today() + timedelta(days=10))
        other = ResourceInstance.objects.create(graph=self.graph)
        self.client_for(self.root).post(
            change_url(embargo),
            {
                "ends_on": embargo.ends_on.isoformat(),
                "state": Embargo.LIFTED,
                "resourceinstance": str(other.pk),
                "events-TOTAL_FORMS": 0,
                "events-INITIAL_FORMS": 0,
            },
        )
        embargo.refresh_from_db()
        self.assertEqual(embargo.state, Embargo.ACTIVE)
        self.assertNotEqual(embargo.resourceinstance_id, other.pk)

    def test_the_extend_action_adds_months_and_records_it(self):
        embargo = self.make(ends_on=date.today() + timedelta(days=30))
        old = embargo.ends_on
        self.client_for(self.admin_user).post(
            LIST_URL, {"action": "extend_3", "_selected_action": [embargo.pk]}
        )
        embargo.refresh_from_db()
        self.assertGreater(embargo.ends_on, old + timedelta(days=80))
        self.assertEqual(embargo.events.get().kind, EmbargoEvent.EXTENDED)

    def test_the_extend_action_stops_at_the_maximum_for_an_administrator(self):
        embargo = self.make(ends_on=date.today() + timedelta(days=300))
        old = embargo.ends_on
        self.client_for(self.admin_user).post(
            LIST_URL, {"action": "extend_12", "_selected_action": [embargo.pk]}
        )
        embargo.refresh_from_db()
        self.assertEqual(embargo.ends_on, old)
        self.assertEqual(embargo.events.count(), 0)

    def test_an_undated_embargo_is_listed_by_the_undated_filter(self):
        dated = self.make(ends_on=date.today() + timedelta(days=30))
        undated = self.make()
        response = self.client_for(self.root).get(LIST_URL, {"dated": "no"})
        rows = response.context["cl"].result_list
        self.assertEqual({row.pk for row in rows}, {undated.pk})

    def test_no_embargo_can_be_deleted_or_added_in_the_admin(self):
        model_admin = admin.site._registry[Embargo]
        request = type("R", (), {"user": self.root})()
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertFalse(model_admin.has_add_permission(request))


class WorkflowCleanupAdminTests(EmbargoTestCase):
    def test_the_ledger_is_listed_but_not_editable(self):
        row = WorkflowCleanup.objects.create(
            workflowid=uuid.uuid4(),
            workflowname="create-project-workflow",
            last_activity=datetime(2026, 7, 1),
        )
        client = self.client_for(self.root)
        url = "/en/admin/manuspectrum/workflowcleanup/"
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(client.post(f"{url}{row.pk}/delete/").status_code, 403)
        self.assertEqual(
            client.post(f"{url}{row.pk}/change/", {"kept_count": 5}).status_code, 403
        )
        row.refresh_from_db()
        self.assertEqual(row.kept_count, 0)


class SettingsTests(TestCase):
    def test_the_cleanup_delay_is_90_days_with_notices_at_21_and_7(self):
        from django.conf import settings

        self.assertEqual(settings.WORKFLOW_CLEANUP_AFTER_DAYS, 90)
        self.assertEqual(tuple(settings.WORKFLOW_NOTICE_DAYS), (21, 7))
        self.assertEqual(settings.EMBARGO_MAX_MONTHS, 12)

    def test_the_activity_report_uses_the_cleanup_delay(self):
        self.assertFalse(hasattr(activity, "WORKFLOW_STALE_AFTER_DAYS"))
        with override_settings(WORKFLOW_CLEANUP_AFTER_DAYS=45):
            figures = activity.collect(
                datetime(2026, 9, 1), datetime(2026, 10, 1), datetime(2026, 10, 12)
            )
        self.assertEqual(figures["workflow_stale_after_days"], 45)


class FrenchLabelTests(TestCase):
    def test_the_admin_labels_are_translated(self):
        from django.utils import translation

        with translation.override("fr"):
            self.assertEqual(str(Embargo._meta.verbose_name), "embargo")
            self.assertEqual(str(Embargo._meta.verbose_name_plural), "embargos")
            self.assertEqual(
                str(dict(EmbargoEvent.KINDS)[EmbargoEvent.EXTENDED]), "Prolongé"
            )
            self.assertEqual(
                str(Embargo._meta.get_field("ends_on").verbose_name), "Se termine le"
            )
