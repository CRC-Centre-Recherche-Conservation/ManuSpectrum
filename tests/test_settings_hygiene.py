"""Invariants of the versioned configuration.

Assertions read ``manuspectrum.settings`` rather than ``django.conf.settings``:
``tests/test_settings.py`` overrides ``CACHES`` and ``MEDIA_ROOT`` for the test
run, and the point here is what a host actually loads. On CI, where no
``settings_local.py`` exists, that module IS the versioned file; on a developer
machine it carries the local mutations too, so a ``settings_local.py`` that
reassigns instead of mutating fails these tests where it is written.
"""

import importlib

from django.test import SimpleTestCase, override_settings
from django.urls import URLResolver, clear_url_caches
from django.views.static import serve

import manuspectrum.settings as project_settings
import manuspectrum.urls

# Raw exports the project ingests. They carry no file signature, so the
# validator admits them by extension only — dropping one from FILE_TYPES makes
# the upload fail with "File type is not permitted".
INSTRUMENT_EXPORTS = {"0", "asd", "csv", "h5", "hdf5", "mca", "tsv", "txt"}


def find_static_serve_mounts(patterns):
    """Patterns THIS URLconf serves with ``django.views.static.serve``.

    Recurses into a resolver built from a pattern list (``i18n_patterns``) but
    not into an ``include()``, whose ``urlconf_name`` is a module: what another
    URLconf mounts is not this file's invariant.
    """
    mounts = []
    for entry in patterns:
        if isinstance(entry, URLResolver):
            if isinstance(entry.urlconf_name, list):
                mounts += find_static_serve_mounts(entry.url_patterns)
        elif getattr(entry, "callback", None) is serve:
            mounts.append(str(entry.pattern))
    return mounts


class FileTypeWhitelistTests(SimpleTestCase):
    def test_instrument_exports_are_accepted(self):
        missing = INSTRUMENT_EXPORTS - set(project_settings.FILE_TYPES)
        self.assertEqual(
            missing,
            set(),
            "FILE_TYPES must cover every format the project ingests; a host "
            "that reassigns it instead of extending it drops these silently.",
        )

    def test_entries_are_bare_lowercase_extensions(self):
        for extension in project_settings.FILE_TYPES:
            self.assertEqual(
                extension,
                extension.lower().lstrip("."),
                "Extensions are compared against file.name.split('.')[-1], "
                "which never yields a leading dot or an uppercase suffix.",
            )

    def test_no_duplicate_entries(self):
        seen = set()
        duplicates = {
            extension
            for extension in project_settings.FILE_TYPES
            if extension in seen or seen.add(extension)
        }
        self.assertEqual(duplicates, set())


class PermissionCacheTests(SimpleTestCase):
    def test_permission_cache_is_not_backed_by_the_database(self):
        backend = project_settings.CACHES["user_permission"]["BACKEND"]
        self.assertNotIn(
            "backends.db",
            backend,
            "Arches reads a pickled permission checker from this cache on "
            "nearly every request.",
        )

    def test_permission_cache_has_its_own_redis_index(self):
        caches = project_settings.CACHES
        self.assertNotEqual(
            caches["user_permission"]["LOCATION"],
            caches["default"]["LOCATION"],
            "A shared index lets a cache flush drop permissions with it.",
        )


class DjangoHostsRemovalTests(SimpleTestCase):
    def test_app_is_not_installed(self):
        self.assertNotIn("django_hosts", project_settings.INSTALLED_APPS)

    def test_no_middleware_remains(self):
        self.assertEqual(
            [m for m in project_settings.MIDDLEWARE if "django_hosts" in m], []
        )

    def test_no_hostconf_points_at_the_project(self):
        # ROOT_HOSTCONF and DEFAULT_HOST come from arches.settings and cannot
        # be unset from here; without the middleware nothing reads them. What
        # must not come back is a project value, which would name a module the
        # project no longer ships.
        self.assertNotEqual(project_settings.ROOT_HOSTCONF, "manuspectrum.hosts")
        self.assertNotEqual(project_settings.DEFAULT_HOST, "manuspectrum")

    def test_hosts_module_is_gone(self):
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("manuspectrum.hosts")


class OutboundFetchBudgetTests(SimpleTestCase):
    def test_budget_is_versioned(self):
        self.assertIsInstance(project_settings.SSRF_TIMEOUT, int)
        self.assertIsInstance(project_settings.SSRF_MAX_REDIRECTS, int)


class MediaExposureTests(SimpleTestCase):
    """MEDIA_ROOT is served as a raw file tree by anything that mounts it.

    That MEDIA_ROOT is still the Python package is a known exposure, tracked in
    settings.py and closed at deployment; what this project controls is not
    adding a mount of its own.
    """

    def reload_urlconf(self):
        importlib.reload(manuspectrum.urls)
        clear_url_caches()

    @override_settings(DEBUG=True)
    def test_project_urlconf_mounts_no_media_catch_all(self):
        # DEBUG is what arms static(); the test runner forces it off, so the
        # URLconf has to be rebuilt to observe what a DEBUG host would get.
        self.addCleanup(self.reload_urlconf)
        self.reload_urlconf()

        self.assertEqual(
            find_static_serve_mounts(manuspectrum.urls.urlpatterns),
            [],
            "A static() mount on MEDIA_URL also shadows the files/<uuid> "
            "route Arches downloads through.",
        )
