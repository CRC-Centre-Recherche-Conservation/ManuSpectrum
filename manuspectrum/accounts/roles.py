"""Who may grant what in the User admin.

A superuser grants everything. Any other staff account that holds the user
permissions (the « Site managers » group, migration 0015) manages ordinary
accounts only:

- it grants the *assignable* groups: those holding no Django permission beyond
  Arches' nodegroup permissions and not named in ``SUPERUSER_ONLY_GROUPS``
  (Arches checks these administrator roles by group name);
- it never changes an account *managed by superusers*: a superuser, a staff
  account (itself included), the visitors' system account, or an account
  holding a direct permission or a group it could not grant.

Staff status, superuser status, direct permissions and passwords are set by
superusers only (`admin.InvitingUserAdmin`).
"""

from django.contrib.auth.models import Group, Permission

from manuspectrum.utils.public_visibility import ANONYMOUS_USERNAME

SITE_MANAGERS = "Site managers"

SUPERUSER_ONLY_GROUPS = (
    SITE_MANAGERS,
    "System Administrator",
    "Application Administrator",
    "RDM Administrator",
    "Mobile Project Administrator",
)

NODEGROUP_PERMISSIONS = ("read_nodegroup", "write_nodegroup", "delete_nodegroup")


def assignable_groups():
    """Groups a non-superuser may grant or withdraw."""
    privileged = Permission.objects.exclude(
        content_type__app_label="models", codename__in=NODEGROUP_PERMISSIONS
    )
    return Group.objects.exclude(name__in=SUPERUSER_ONLY_GROUPS).exclude(
        permissions__in=privileged
    )


def managed_by_superusers(user):
    """True when only a superuser may change or delete this account."""
    if user.is_superuser or user.is_staff or user.username == ANONYMOUS_USERNAME:
        return True
    if user.user_permissions.exists():
        return True
    return user.groups.exclude(pk__in=assignable_groups().values("pk")).exists()
