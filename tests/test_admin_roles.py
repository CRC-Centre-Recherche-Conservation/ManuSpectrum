"""Roles in the User admin: what a staff account that is not a superuser may grant.

Usage:
    python manage.py test tests.test_admin_roles --settings="tests.test_settings" --noinput
"""

import importlib
from datetime import date, timedelta

from arches.app.models.models import GraphModel, ResourceInstance
from django.contrib.auth.models import Group, Permission, User
from django.core import mail
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.operations.special import RunPython
from django.test import Client, TestCase
from django.urls import reverse

from manuspectrum.accounts import roles
from manuspectrum.models import Embargo

PASSWORD = "Str0ng!Passphrase-for-tests"
MIGRATION = "manuspectrum.migrations.0015_site_managers_group"
EXPECTED_PERMISSIONS = {
    "auth.add_user",
    "auth.change_user",
    "auth.view_user",
    "manuspectrum.add_sitenotice",
    "manuspectrum.change_sitenotice",
    "manuspectrum.delete_sitenotice",
    "manuspectrum.view_sitenotice",
    "manuspectrum.change_embargo",
    "manuspectrum.view_embargo",
    "manuspectrum.view_embargoevent",
    "manuspectrum.view_termsacceptance",
    "manuspectrum.view_workflowcleanup",
}


def change_url(user):
    return reverse("admin:auth_user_change", args=[user.pk])


def password_url(user):
    return reverse("admin:auth_user_password_change", args=[user.pk])


def change_payload(user, **extra):
    data = {
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_active": "on",
        "date_joined_0": "2026-01-01",
        "date_joined_1": "10:00:00",
    }
    data.update(extra)
    return data


class RoleCase(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.boss = User.objects.create_superuser(
            "boss", "boss@manuspectrum.test", PASSWORD
        )
        self.manager = User.objects.create_user(
            "manager", "manager@manuspectrum.test", PASSWORD, is_staff=True
        )
        self.manager.groups.add(Group.objects.get(name=roles.SITE_MANAGERS))
        self.alice = User.objects.create_user(
            "alice", "alice@manuspectrum.test", PASSWORD
        )
        self.editor_group = Group.objects.get(name="Resource Editor")
        self.client = Client(raise_request_exception=False)
        self.client.force_login(self.manager)

    def privileged_groups(self):
        return list(
            Group.objects.filter(
                name__in=(roles.SITE_MANAGERS, "System Administrator")
            ).values_list("pk", flat=True)
        )


class ElevationTests(RoleCase):
    def test_a_forged_post_cannot_elevate_another_account(self):
        perms = Permission.objects.filter(codename__in=("change_user", "add_group"))
        response = self.client.post(
            change_url(self.alice),
            change_payload(
                self.alice,
                is_staff="on",
                is_superuser="on",
                user_permissions=[p.pk for p in perms],
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_superuser)
        self.assertFalse(self.alice.is_staff)
        self.assertFalse(self.alice.user_permissions.exists())

    def test_a_privileged_group_cannot_be_granted(self):
        for pk in self.privileged_groups():
            response = self.client.post(
                change_url(self.alice), change_payload(self.alice, groups=[pk])
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["adminform"].form.errors)
        self.assertFalse(self.alice.groups.exists())

    def test_an_editor_group_can_be_granted_and_withdrawn(self):
        response = self.client.post(
            change_url(self.alice),
            change_payload(self.alice, groups=[self.editor_group.pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.alice.groups.filter(pk=self.editor_group.pk).exists())
        self.client.post(change_url(self.alice), change_payload(self.alice))
        self.assertFalse(self.alice.groups.exists())

    def test_a_forged_post_cannot_change_identity_or_dates(self):
        joined = self.alice.date_joined
        response = self.client.post(
            change_url(self.alice),
            change_payload(
                self.alice,
                username="hijacked",
                email="manager-alias@manuspectrum.test",
                last_login_0="2020-01-01",
                last_login_1="10:00:00",
                date_joined_0="2020-01-01",
                date_joined_1="10:00:00",
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.username, "alice")
        self.assertEqual(self.alice.email, "alice@manuspectrum.test")
        self.assertIsNone(self.alice.last_login)
        self.assertEqual(self.alice.date_joined, joined)

    def test_the_assignable_set_among_arches_default_groups(self):
        self.assertEqual(
            set(roles.assignable_groups().values_list("name", flat=True)),
            {
                "Crowdsource Editor",
                "Graph Editor",
                "Guest",
                "Resource Editor",
                "Resource Exporter",
                "Resource Reviewer",
            },
        )

    def test_the_groups_offered_are_the_assignable_ones(self):
        response = self.client.get(change_url(self.alice))
        offered = set(
            response.context["adminform"]
            .form.fields["groups"]
            .queryset.values_list("name", flat=True)
        )
        self.assertIn("Resource Editor", offered)
        for name in roles.SUPERUSER_ONLY_GROUPS:
            self.assertNotIn(name, offered)

    def test_privilege_fields_are_read_only(self):
        response = self.client.get(change_url(self.alice))
        adminform = response.context["adminform"]
        shown = {
            field
            for _name, options in adminform.fieldsets
            for field in options["fields"]
        }
        for name in ("is_staff", "is_superuser", "user_permissions"):
            self.assertNotIn(name, adminform.form.fields)
            self.assertIn(name, adminform.readonly_fields)
        self.assertNotIn("password", shown)
        self.assertNotContains(response, "../password/")

    def test_the_own_account_cannot_be_changed(self):
        response = self.client.post(
            change_url(self.manager),
            change_payload(
                self.manager,
                is_staff="on",
                is_superuser="on",
                groups=self.privileged_groups(),
            ),
        )
        self.assertEqual(response.status_code, 403)
        self.manager.refresh_from_db()
        self.assertFalse(self.manager.is_superuser)
        self.assertEqual(
            list(self.manager.groups.values_list("name", flat=True)),
            [roles.SITE_MANAGERS],
        )

    def test_the_add_form_refuses_a_privileged_group(self):
        url = reverse("admin:auth_user_add")
        base = {"username": "newbie", "email": "newbie@manuspectrum.test"}
        response = self.client.post(url, {**base, "groups": self.privileged_groups()})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newbie").exists())
        response = self.client.post(url, {**base, "groups": [self.editor_group.pk]})
        self.assertEqual(response.status_code, 302)
        newbie = User.objects.get(username="newbie")
        self.assertEqual(list(newbie.groups.all()), [self.editor_group])


class ProtectedAccountTests(RoleCase):
    def test_a_superuser_is_read_only(self):
        response = self.client.get(change_url(self.boss))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["has_change_permission"])
        response = self.client.post(
            change_url(self.boss),
            change_payload(self.boss, email="taken@manuspectrum.test"),
        )
        self.assertEqual(response.status_code, 403)
        self.boss.refresh_from_db()
        self.assertEqual(self.boss.email, "boss@manuspectrum.test")

    def test_no_password_can_be_set_by_a_non_superuser(self):
        for target in (self.boss, self.alice, self.manager):
            self.assertEqual(self.client.get(password_url(target)).status_code, 403)
            response = self.client.post(
                password_url(target),
                {
                    "password1": "An0ther!Passphrase-x",
                    "password2": "An0ther!Passphrase-x",
                    "set_usable_password": "true",
                },
            )
            self.assertEqual(response.status_code, 403)
        self.boss.refresh_from_db()
        self.assertTrue(self.boss.check_password(PASSWORD))

    def test_other_staff_anonymous_and_privileged_members_are_read_only(self):
        other = User.objects.create_user("other", "o@manuspectrum.test", is_staff=True)
        admin_member = User.objects.create_user("sysadmin", "s@manuspectrum.test")
        admin_member.groups.add(Group.objects.get(name="System Administrator"))
        holder = User.objects.create_user("holder", "h@manuspectrum.test")
        holder.user_permissions.add(Permission.objects.get(codename="view_user"))
        anonymous = User.objects.get(username="anonymous")
        for target in (other, admin_member, holder, anonymous):
            response = self.client.post(change_url(target), change_payload(target))
            self.assertEqual(response.status_code, 403, target.username)

    def test_a_staff_with_delete_permission_cannot_delete_a_superuser(self):
        self.manager.user_permissions.add(
            Permission.objects.get(codename="delete_user")
        )
        response = self.client.post(
            reverse("admin:auth_user_delete", args=[self.boss.pk]), {"post": "yes"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.boss.pk).exists())

    def test_bulk_delete_of_a_superuser_is_refused(self):
        self.manager.user_permissions.add(
            Permission.objects.get(codename="delete_user")
        )
        self.client.post(
            reverse("admin:auth_user_changelist"),
            {
                "action": "delete_selected",
                "_selected_action": [self.boss.pk],
                "post": "yes",
            },
        )
        self.assertTrue(User.objects.filter(pk=self.boss.pk).exists())

    def test_invitations_skip_protected_accounts(self):
        held = User.objects.create_user("held", "held@manuspectrum.test", is_staff=True)
        fresh = User.objects.create_user("fresh", "fresh@manuspectrum.test")
        response = self.client.post(
            reverse("admin:auth_user_changelist"),
            {"action": "send_invitation", "_selected_action": [held.pk, fresh.pk]},
            follow=True,
        )
        self.assertEqual([m.to for m in mail.outbox], [["fresh@manuspectrum.test"]])
        self.assertContains(response, "1 account was skipped")


class SuperuserTests(RoleCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.boss)

    def test_a_superuser_appoints_a_manager(self):
        group = Group.objects.get(name=roles.SITE_MANAGERS)
        response = self.client.post(
            change_url(self.alice),
            change_payload(self.alice, is_staff="on", groups=[group.pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.is_staff)
        self.assertTrue(self.alice.groups.filter(pk=group.pk).exists())

    def test_a_superuser_may_set_any_password(self):
        response = self.client.post(
            password_url(self.manager),
            {
                "password1": "An0ther!Passphrase-x",
                "password2": "An0ther!Passphrase-x",
                "set_usable_password": "true",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.manager.refresh_from_db()
        self.assertTrue(self.manager.check_password("An0ther!Passphrase-x"))

    def test_the_change_form_keeps_every_field(self):
        response = self.client.get(change_url(self.manager))
        form = response.context["adminform"].form
        for name in ("is_staff", "is_superuser", "user_permissions", "password"):
            self.assertIn(name, form.fields)
        self.assertTrue(response.context["has_change_permission"])


class SiteManagersGroupTests(RoleCase):
    def granted(self):
        group = Group.objects.get(name=roles.SITE_MANAGERS)
        return {
            f"{p.content_type.app_label}.{p.codename}"
            for p in group.permissions.select_related("content_type")
        }

    def test_the_group_holds_exactly_its_permissions(self):
        self.assertEqual(self.granted(), EXPECTED_PERMISSIONS)

    def test_the_migration_is_idempotent_and_keeps_members_on_reverse(self):
        migration = importlib.import_module(MIGRATION)
        historical = (
            MigrationExecutor(connection)
            .loader.project_state(("manuspectrum", "0015_site_managers_group"))
            .apps
        )
        group = Group.objects.get(name=roles.SITE_MANAGERS)
        group.permissions.add(Permission.objects.get(codename="delete_user"))
        editor = connection.schema_editor()
        migration.create_group(historical, editor)
        migration.create_group(historical, editor)
        self.assertEqual(self.granted(), EXPECTED_PERMISSIONS)
        self.assertEqual(Group.objects.filter(name=roles.SITE_MANAGERS).count(), 1)
        self.assertTrue(self.manager.groups.filter(pk=group.pk).exists())
        (operation,) = migration.Migration.operations
        self.assertIs(operation.reverse_code, RunPython.noop)

    def test_a_manager_reaches_the_listed_admin_pages(self):
        for name in (
            "admin:auth_user_changelist",
            "admin:auth_user_add",
            "admin:manuspectrum_sitenotice_changelist",
            "admin:manuspectrum_sitenotice_add",
            "admin:manuspectrum_embargo_changelist",
            "admin:manuspectrum_termsacceptance_changelist",
            "admin:manuspectrum_workflowcleanup_changelist",
        ):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_a_manager_reaches_nothing_else(self):
        for name in (
            "admin:auth_group_changelist",
            "admin:auth_group_add",
            "admin:oauth2_provider_application_changelist",
            "admin:oauth2_provider_accesstoken_changelist",
            "admin:models_userprofile_changelist",
            "admin:auth_user_delete",
        ):
            args = [self.alice.pk] if name.endswith("_delete") else []
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 403, name)

    def test_the_ledgers_are_view_only(self):
        for name in (
            "admin:manuspectrum_termsacceptance_add",
            "admin:manuspectrum_workflowcleanup_add",
        ):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_membership_without_staff_status_opens_no_admin(self):
        self.manager.is_staff = False
        self.manager.save()
        response = self.client.get(reverse("admin:auth_user_changelist"))
        self.assertEqual(response.status_code, 302)


class EmbargoActionTests(RoleCase):
    def setUp(self):
        super().setUp()
        viewer = User.objects.create_user(
            "viewer", "v@manuspectrum.test", PASSWORD, is_staff=True
        )
        viewer.user_permissions.add(Permission.objects.get(codename="view_embargo"))
        self.client.force_login(viewer)

    def test_extending_needs_the_change_permission(self):
        response = self.client.get(reverse("admin:manuspectrum_embargo_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["action_form"])

    def test_a_forged_extend_by_a_viewer_changes_nothing(self):
        graph = GraphModel.objects.create(
            name="roles_model", isresource=True, is_active=True, slug="roles_model"
        )
        resource = ResourceInstance.objects.create(
            graph=graph, descriptors={"en": {"name": "Codex R"}}
        )
        ends_on = date.today() + timedelta(days=30)
        embargo = Embargo.objects.create(resourceinstance=resource, ends_on=ends_on)
        self.client.post(
            reverse("admin:manuspectrum_embargo_changelist"),
            {"action": "extend_3", "_selected_action": [embargo.pk]},
        )
        embargo.refresh_from_db()
        self.assertEqual(embargo.ends_on, ends_on)
