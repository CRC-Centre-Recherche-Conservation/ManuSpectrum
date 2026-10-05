import os
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from manuspectrum import tasks
from manuspectrum.observability import celery_signals
from tests.observability_helpers import delta, sample


def task(name):
    return SimpleNamespace(name=name, request=SimpleNamespace())


class TaskMetricsTests(SimpleTestCase):
    def run_task(self, name, state):
        celery_signals.bind_task(task_id="t1", task=task(name))
        celery_signals.unbind_task(task_id="t1", task=task(name), state=state)

    def test_outcomes_and_run_time(self):
        name = "manuspectrum.prune_data_changes"
        with (
            delta(
                "manuspectrum_celery_tasks_total", task=name, outcome="success"
            ) as ok,
            delta(
                "manuspectrum_celery_tasks_total", task=name, outcome="failure"
            ) as failed,
            delta("manuspectrum_celery_task_seconds_count", task=name) as timed,
        ):
            self.run_task(name, "SUCCESS")
            self.run_task(name, "FAILURE")
        self.assertEqual((ok.value, failed.value, timed.value), (1, 1, 2))

    def test_unknown_task_names_are_folded(self):
        with delta(
            "manuspectrum_celery_tasks_total", task="other", outcome="other"
        ) as folded:
            self.run_task("thirdparty.task", "REVOKED")
        self.assertEqual(folded.value, 1)


class WorkerEndpointTests(SimpleTestCase):
    def test_nothing_without_port_or_directory(self):
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("prometheus_client.start_http_server") as start,
        ):
            os.environ.pop("MS_CELERY_METRICS_PORT", None)
            celery_signals.serve_worker_metrics()
        start.assert_not_called()

    def test_serves_the_multiprocess_registry_on_the_port(self):
        with (
            patch.dict(
                os.environ,
                {"MS_CELERY_METRICS_PORT": "9808", "PROMETHEUS_MULTIPROC_DIR": "/tmp"},
            ),
            patch("prometheus_client.start_http_server") as start,
            patch("prometheus_client.multiprocess.MultiProcessCollector") as collector,
        ):
            celery_signals.serve_worker_metrics()
        self.assertEqual(start.call_args.args[0], 9808)
        self.assertEqual(
            start.call_args.kwargs["registry"], collector.call_args.args[0]
        )

    def test_a_child_that_exits_is_marked_dead(self):
        with (
            patch.dict(os.environ, {"PROMETHEUS_MULTIPROC_DIR": "/tmp"}),
            patch("prometheus_client.multiprocess.mark_process_dead") as dead,
        ):
            celery_signals.forget_child(pid=4242)
        dead.assert_called_once_with(4242)


class IndexTaskTests(TestCase):
    def test_resource_outcomes(self):
        from arches.app.models.resource import Resource

        with (
            patch.object(Resource.objects, "get", side_effect=Resource.DoesNotExist),
            delta(
                "manuspectrum_index_resources_total",
                mode="resource",
                outcome="not_found",
            ) as missing,
        ):
            tasks.index_resources_async(resource_ids=["a", "b"])
        self.assertEqual(missing.value, 2)

    def test_transaction_mode(self):
        with (
            patch("arches.app.utils.index_database.index_resources_by_transaction"),
            delta(
                "manuspectrum_index_resources_total",
                mode="transaction",
                outcome="indexed",
            ) as indexed,
        ):
            tasks.index_resources_async(transaction_id="tx")
        self.assertEqual(indexed.value, 1)


class PruneTaskTests(TestCase):
    def test_the_ledger_size_and_prune_time_are_recorded(self):
        tasks.prune_data_changes_task()
        self.assertGreater(
            sample("manuspectrum_data_change_pruned_timestamp_seconds"), 0
        )
        self.assertGreaterEqual(sample("manuspectrum_data_change_rows"), 0)
