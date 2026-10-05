import time
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from manuspectrum.views.explorer import memo
from tests.observability_helpers import delta, sample


@override_settings(LANGUAGES=[("en", "English"), ("fr", "French")])
class BundleMetricsTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_a_build_records_duration_size_rows_and_reason(self):
        bundle = SimpleNamespace(rows=[1, 2, 3])
        with (
            delta(
                "manuspectrum_explorer_bundle_builds_total",
                language="fr",
                reason="data",
                background="true",
            ) as builds,
            delta(
                "manuspectrum_explorer_bundle_build_seconds_count", language="fr"
            ) as observed,
        ):
            memo._log_build(
                "explorer-bundle:k",
                "fr",
                "data",
                time.monotonic() - 2,
                bundle,
                b"x" * 1234,
                True,
            )
        self.assertEqual((builds.value, observed.value), (1, 1))
        self.assertEqual(
            sample("manuspectrum_explorer_bundle_bytes", language="fr"), 1234
        )
        self.assertEqual(sample("manuspectrum_explorer_bundle_rows", language="fr"), 3)

    def test_an_unknown_language_or_reason_is_folded(self):
        with delta(
            "manuspectrum_explorer_bundle_builds_total",
            language="other",
            reason="other",
            background="false",
        ) as builds:
            memo._log_build(
                "explorer-bundle:k",
                "xx",
                "weird",
                time.monotonic(),
                SimpleNamespace(rows=[]),
                b"",
                False,
            )
        self.assertEqual(builds.value, 1)

    def test_stale_answers_are_counted(self):
        held = SimpleNamespace(current="explorer-bundle:k2", language="en")
        with delta("manuspectrum_explorer_stale_served_total", language="en") as stale:
            memo._count_stale(held)
        self.assertEqual(stale.value, 1)

    @override_settings(
        EXPLORER_BACKGROUND_REBUILD=False, EXPLORER_REBUILD_MIN_INTERVAL=0
    )
    def test_a_failed_background_rebuild_is_counted(self):
        held = SimpleNamespace(
            current="explorer-bundle:k3", language="en", reason="data"
        )
        with (
            patch.object(memo, "_build_and_keep", side_effect=RuntimeError("boom")),
            delta(
                "manuspectrum_explorer_rebuild_failures_total", language="en"
            ) as failures,
        ):
            memo._rebuild_in_background(held, None, lambda *a: None)
        self.assertEqual(failures.value, 1)


class ExportBytesTests(TestCase):
    def test_the_declared_length_is_observed(self):
        from manuspectrum.views.explorer import export

        scope = SimpleNamespace(kind="ids", digest="d")
        request = RequestFactory().get("/api/explorer/export", {"ids": "x"})
        with (
            patch.object(export, "export_language", return_value="en"),
            patch.object(export, "resolve_scope", return_value=scope),
            patch.object(export, "_assemble", return_value=([], {})),
            patch.object(export, "ro_crate", return_value={}),
            patch.object(export, "stream", return_value=(3 * 1024 * 1024, iter([b""]))),
            delta("manuspectrum_explorer_export_bytes_count") as exports,
            delta("manuspectrum_explorer_export_bytes_sum") as total,
        ):
            export.ExplorerExportView().get(request)
        self.assertEqual((exports.value, total.value), (1, 3 * 1024 * 1024))
