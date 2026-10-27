"""The « Site managers » group: accounts, site announcements, embargo dates, ledgers.

The name is a stable English identifier, like Arches' own groups. Members also
need staff status to reach the admin; both are granted by a superuser
(`accounts/roles.py`). Running it again resets the group to exactly these
permissions; reversing it leaves the group and its members in place. A later
change of these permissions is a new data migration.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

GROUP = "Site managers"

PERMISSIONS = (
    ("auth", "add_user"),
    ("auth", "change_user"),
    ("auth", "view_user"),
    ("manuspectrum", "add_sitenotice"),
    ("manuspectrum", "change_sitenotice"),
    ("manuspectrum", "delete_sitenotice"),
    ("manuspectrum", "view_sitenotice"),
    ("manuspectrum", "change_embargo"),
    ("manuspectrum", "view_embargo"),
    ("manuspectrum", "view_embargoevent"),
    ("manuspectrum", "view_termsacceptance"),
    ("manuspectrum", "view_workflowcleanup"),
)


def create_group(apps, schema_editor):
    # Permissions are otherwise created after the last migration (post_migrate).
    for label in ("auth", "manuspectrum"):
        config = apps.get_app_config(label)
        previous = getattr(config, "models_module", None)
        config.models_module = True
        try:
            create_permissions(
                config, verbosity=0, using=schema_editor.connection.alias, apps=apps
            )
        finally:
            config.models_module = previous
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    group, _ = Group.objects.get_or_create(name=GROUP)
    permissions = [
        Permission.objects.get(content_type__app_label=app, codename=codename)
        for app, codename in PERMISSIONS
    ]
    group.permissions.set(permissions)


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("manuspectrum", "0014_site_notice"),
    ]

    operations = [migrations.RunPython(create_group, migrations.RunPython.noop)]
