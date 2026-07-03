"""Unit tests for Phase 4 — async ES indexing seam.

Covers:
  4.1 — ``index_resources_async`` Celery task (eager mode, no real broker).
  4.2 — ``BiblissimaCreateResourceView._defer_indexing`` seam:
         * flag OFF  → sync path runs, ``.delay`` never called
         * flag ON + ``.delay`` raises ``OperationalError`` → sync fallback
         * flag ON + broker OK → ``.delay`` called, sync NOT called
  4.3 — Startup assertion in ``ManuspectrumConfig._check_async_indexing_config``:
         task missing from registry + flag ON → logs error + sets flag False.

Patching strategy
-----------------
- Celery task ``index_resources_async`` is called in *eager* mode
  (``.apply(args=...)`` / ``.apply(kwargs=...)``) — no real broker needed.
- ``index_resources_by_transaction`` and ``Resource`` are patched at their
  source modules (local imports inside the task/seam).
- ``_defer_indexing`` wraps work in ``transaction.on_commit``; tests use
  ``self.captureOnCommitCallbacks(execute=True)`` to fire callbacks
  synchronously so assertions on sync/async dispatch can be made inside the
  test body.

Run:
    /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_indexing_unit --settings="tests.test_settings" \\
        --noinput
"""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from django.test import TestCase, override_settings

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------
PATCH_INDEX_TX = "arches.app.utils.index_database.index_resources_by_transaction"
PATCH_RESOURCE = "arches.app.models.resource.Resource"
# The task is imported inside the on_commit callback so we patch it at its
# canonical module path, which is what the deferred import resolves to.
PATCH_TASK = "manuspectrum.tasks.index_resources_async"


# ===========================================================================
# Task 4.1 — index_resources_async (eager, no broker)
# ===========================================================================


class IndexResourcesAsyncTxTests(TestCase):
    """Transaction-id branch: must call index_resources_by_transaction once
    with recalculate_descriptors=True."""

    def test_calls_index_by_transaction_with_recalculate(self):
        from manuspectrum.tasks import index_resources_async

        tx_id = str(uuid.uuid4())
        with patch(PATCH_INDEX_TX) as mock_index:
            index_resources_async.apply(kwargs={"transaction_id": tx_id})

        mock_index.assert_called_once_with(tx_id, recalculate_descriptors=True)

    def test_resource_ids_branch_not_called_when_tx_given(self):
        """When transaction_id is given, the resource_ids branch must not run."""
        from manuspectrum.tasks import index_resources_async

        tx_id = str(uuid.uuid4())
        resource_id = str(uuid.uuid4())
        with patch(PATCH_INDEX_TX) as mock_index, patch(PATCH_RESOURCE) as mock_res:
            index_resources_async.apply(
                kwargs={"transaction_id": tx_id, "resource_ids": [resource_id]}
            )

        mock_index.assert_called_once()
        mock_res.objects.get.assert_not_called()


class IndexResourcesAsyncRidsTests(TestCase):
    """resource_ids branch: must call resource.index() for each id."""

    def test_indexes_each_resource(self):
        from manuspectrum.tasks import index_resources_async

        rid_a = str(uuid.uuid4())
        rid_b = str(uuid.uuid4())
        mock_resource_a = MagicMock()
        mock_resource_b = MagicMock()

        def _get(pk):
            return {rid_a: mock_resource_a, rid_b: mock_resource_b}[str(pk)]

        with patch(PATCH_RESOURCE) as mock_cls:
            mock_cls.objects.get.side_effect = _get
            index_resources_async.apply(kwargs={"resource_ids": [rid_a, rid_b]})

        mock_resource_a.index.assert_called_once()
        mock_resource_b.index.assert_called_once()

    def test_missing_resource_skipped_not_raised(self):
        """DoesNotExist for one resource must not abort indexing of the others."""
        from manuspectrum.tasks import index_resources_async
        from arches.app.models.resource import Resource

        rid_missing = str(uuid.uuid4())
        rid_ok = str(uuid.uuid4())
        mock_resource_ok = MagicMock()

        def _get(pk):
            if str(pk) == rid_missing:
                raise Resource.DoesNotExist
            return mock_resource_ok

        with patch(PATCH_RESOURCE) as mock_cls:
            mock_cls.DoesNotExist = Resource.DoesNotExist
            mock_cls.objects.get.side_effect = _get
            # Must not raise
            index_resources_async.apply(
                kwargs={"resource_ids": [rid_missing, rid_ok]}
            )

        mock_resource_ok.index.assert_called_once()

    def test_no_args_is_noop(self):
        """Calling with neither arg must not raise."""
        from manuspectrum.tasks import index_resources_async

        with patch(PATCH_INDEX_TX) as mock_index, patch(PATCH_RESOURCE) as mock_res:
            index_resources_async.apply(kwargs={})  # neither arg

        mock_index.assert_not_called()
        mock_res.objects.get.assert_not_called()


# ===========================================================================
# Task 4.2 — _defer_indexing seam
# ===========================================================================


def _make_view():
    """Return a bare BiblissimaCreateResourceView (no DB dependency)."""
    from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

    return BiblissimaCreateResourceView()


class DeferIndexingFlagOffTests(TestCase):
    """BIBLISSIMA_ASYNC_INDEXING=False (default) → sync path, no .delay call.

    Important nesting order: the mock patches must be the OUTER context so they
    are still active when captureOnCommitCallbacks fires the on_commit callbacks
    on its own __exit__.
    """

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=False)
    def test_tx_id_path_calls_index_by_transaction_sync(self):
        view = _make_view()
        tx_id = uuid.uuid4()

        with patch(PATCH_INDEX_TX) as mock_index, patch(PATCH_TASK) as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                view._defer_indexing(tx_id=tx_id)

        mock_index.assert_called_once_with(str(tx_id), recalculate_descriptors=True)
        mock_task.delay.assert_not_called()

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=False)
    def test_resource_ids_path_calls_index_sync(self):
        view = _make_view()
        rid = str(uuid.uuid4())
        mock_resource = MagicMock()

        with patch(PATCH_RESOURCE) as mock_cls, patch(PATCH_TASK) as mock_task:
            mock_cls.objects.get.return_value = mock_resource
            with self.captureOnCommitCallbacks(execute=True):
                view._defer_indexing(resource_ids=[rid])

        mock_resource.index.assert_called_once()
        mock_task.delay.assert_not_called()

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=False)
    def test_delay_never_called_when_flag_off(self):
        """Regardless of whether the task exists, .delay must not be called."""
        view = _make_view()
        tx_id = uuid.uuid4()

        with patch(PATCH_INDEX_TX), patch(PATCH_TASK) as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                view._defer_indexing(tx_id=tx_id)

        mock_task.delay.assert_not_called()


class DeferIndexingFlagOnBrokerFailTests(TestCase):
    """BIBLISSIMA_ASYNC_INDEXING=True + .delay raises OperationalError
    → falls back to synchronous indexing, resource is still indexed.

    Patches are the OUTER context so they remain active when on_commit callbacks
    fire inside captureOnCommitCallbacks.__exit__.
    """

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=True)
    def test_operational_error_falls_back_to_sync_tx(self):
        from kombu.exceptions import OperationalError

        view = _make_view()
        tx_id = uuid.uuid4()

        with patch(PATCH_INDEX_TX) as mock_index, patch(PATCH_TASK) as mock_task:
            mock_task.delay.side_effect = OperationalError("broker down")
            with self.captureOnCommitCallbacks(execute=True):
                view._defer_indexing(tx_id=tx_id)

        # Async dispatch was attempted
        mock_task.delay.assert_called_once()
        # Sync fallback ran
        mock_index.assert_called_once_with(str(tx_id), recalculate_descriptors=True)

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=True)
    def test_connection_error_falls_back_to_sync_rids(self):
        view = _make_view()
        rid = str(uuid.uuid4())
        mock_resource = MagicMock()

        with patch(PATCH_RESOURCE) as mock_cls, patch(PATCH_TASK) as mock_task:
            mock_cls.objects.get.return_value = mock_resource
            mock_task.delay.side_effect = ConnectionError("no broker")
            with self.captureOnCommitCallbacks(execute=True):
                view._defer_indexing(resource_ids=[rid])

        mock_task.delay.assert_called_once()
        mock_resource.index.assert_called_once()

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=True)
    def test_generic_exception_from_delay_falls_back_to_sync(self):
        """Any exception from .delay (not just OperationalError/ConnectionError)
        must trigger the sync fallback — the resource must always be indexed."""
        view = _make_view()
        tx_id = uuid.uuid4()

        with patch(PATCH_INDEX_TX) as mock_index, patch(PATCH_TASK) as mock_task:
            mock_task.delay.side_effect = RuntimeError("unexpected broker error")
            with self.captureOnCommitCallbacks(execute=True):
                view._defer_indexing(tx_id=tx_id)

        mock_task.delay.assert_called_once()
        mock_index.assert_called_once_with(str(tx_id), recalculate_descriptors=True)


class DeferIndexingFlagOnBrokerOkTests(TestCase):
    """BIBLISSIMA_ASYNC_INDEXING=True + broker OK → .delay called, sync NOT called.

    Patches are the OUTER context so they remain active when on_commit callbacks
    fire inside captureOnCommitCallbacks.__exit__.
    """

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=True)
    def test_tx_id_dispatched_async_no_sync(self):
        view = _make_view()
        tx_id = uuid.uuid4()

        with patch(PATCH_INDEX_TX) as mock_index, patch(PATCH_TASK) as mock_task:
            mock_task.delay.return_value = MagicMock()  # no exception
            with self.captureOnCommitCallbacks(execute=True):
                view._defer_indexing(tx_id=tx_id)

        mock_task.delay.assert_called_once_with(transaction_id=str(tx_id))
        mock_index.assert_not_called()

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=True)
    def test_resource_ids_dispatched_async_no_sync(self):
        view = _make_view()
        rid = str(uuid.uuid4())

        with patch(PATCH_RESOURCE) as mock_cls, patch(PATCH_TASK) as mock_task:
            mock_task.delay.return_value = MagicMock()
            with self.captureOnCommitCallbacks(execute=True):
                view._defer_indexing(resource_ids=[rid])

        mock_task.delay.assert_called_once_with(resource_ids=[rid])
        mock_cls.objects.get.assert_not_called()

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=True)
    def test_on_commit_is_used_not_inline(self):
        """Without captureOnCommitCallbacks, no indexing occurs — verifying
        that the seam truly defers work to on_commit and does not run inline."""
        view = _make_view()
        tx_id = uuid.uuid4()

        with patch(PATCH_INDEX_TX) as mock_index, patch(PATCH_TASK) as mock_task:
            # NO captureOnCommitCallbacks — callbacks should NOT fire here
            view._defer_indexing(tx_id=tx_id)

        mock_task.delay.assert_not_called()
        mock_index.assert_not_called()


# ===========================================================================
# Task 4.3 — startup assertion (ManuspectrumConfig._check_async_indexing_config)
# ===========================================================================


class StartupAssertionTests(TestCase):
    """_check_async_indexing_config must detect missing task and disable flag."""

    def _run_check(self, async_flag, tasks_registered):
        """Run ``_check_async_indexing_config`` with controlled settings and a
        Celery app stub whose ``.tasks`` dict is controlled by *tasks_registered*."""
        from manuspectrum.apps import ManuspectrumConfig

        config = ManuspectrumConfig.__new__(ManuspectrumConfig)

        # Build a fake Celery app whose .tasks dict is controllable.
        fake_tasks = {"manuspectrum.index_resources": object()} if tasks_registered else {}
        fake_celery_app = SimpleNamespace(tasks=fake_tasks)

        with override_settings(BIBLISSIMA_ASYNC_INDEXING=async_flag):
            with patch(
                "manuspectrum.apps.settings",
                BIBLISSIMA_ASYNC_INDEXING=async_flag,
            ) as mock_settings, patch(
                "manuspectrum.celery.app", fake_celery_app
            ):
                # Patch the import inside _check_async_indexing_config so it
                # returns our stub rather than requiring a real Celery connection.
                with patch(
                    "manuspectrum.apps.ManuspectrumConfig._check_async_indexing_config",
                    autospec=True,
                ) as _:
                    pass  # We call the REAL method below, not the patched one.

                # Actually call the real method under controlled conditions.
                # We need to patch the import path inside the method body.
                import manuspectrum.apps as apps_module

                original_check = ManuspectrumConfig._check_async_indexing_config
                with patch.object(apps_module, "settings", mock_settings):
                    with patch(
                        "manuspectrum.celery.app", fake_celery_app, create=True
                    ):
                        original_check(config)

            return mock_settings

    def test_flag_off_check_is_noop(self):
        """When BIBLISSIMA_ASYNC_INDEXING=False, the check does nothing."""
        import manuspectrum.apps as apps_module

        mock_settings = MagicMock(BIBLISSIMA_ASYNC_INDEXING=False)
        from manuspectrum.apps import ManuspectrumConfig

        config = ManuspectrumConfig.__new__(ManuspectrumConfig)
        with patch.object(apps_module, "settings", mock_settings):
            ManuspectrumConfig._check_async_indexing_config(config)

        # No attempt to import celery or check tasks (getattr returns False quickly).
        # Just assert the flag wasn't changed.
        self.assertFalse(mock_settings.BIBLISSIMA_ASYNC_INDEXING)

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=True)
    def test_task_missing_disables_flag_and_logs_error(self):
        """When the task is NOT registered and flag is ON, the flag is set to
        False and an error is logged."""
        import manuspectrum.apps as apps_module
        from manuspectrum.apps import ManuspectrumConfig

        config = ManuspectrumConfig.__new__(ManuspectrumConfig)
        # Celery app stub without the task registered.
        fake_celery_app = SimpleNamespace(tasks={})

        with patch.object(apps_module, "settings") as mock_settings, \
             patch("manuspectrum.apps.ManuspectrumConfig._import_celery_app",
                   return_value=fake_celery_app, create=True):
            mock_settings.BIBLISSIMA_ASYNC_INDEXING = True

            # Patch the import inside _check_async_indexing_config.
            import sys
            fake_celery_module = SimpleNamespace(app=fake_celery_app)

            original_modules = sys.modules.copy()
            sys.modules["manuspectrum.celery"] = fake_celery_module  # type: ignore[assignment]
            try:
                with self.assertLogs("manuspectrum.apps", level="ERROR") as cm:
                    ManuspectrumConfig._check_async_indexing_config(config)
            finally:
                # Restore original module state.
                sys.modules.pop("manuspectrum.celery", None)
                if "manuspectrum.celery" in original_modules:
                    sys.modules["manuspectrum.celery"] = original_modules[
                        "manuspectrum.celery"
                    ]

        # Flag must be set to False.
        self.assertFalse(mock_settings.BIBLISSIMA_ASYNC_INDEXING)
        # Error must be logged.
        self.assertTrue(
            any("index_resources" in msg for msg in cm.output),
            f"Expected error about index_resources in logs; got: {cm.output}",
        )

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=True)
    def test_task_registered_flag_stays_true(self):
        """When the task IS registered and flag is ON, the flag stays True."""
        import sys
        import manuspectrum.apps as apps_module
        from manuspectrum.apps import ManuspectrumConfig

        config = ManuspectrumConfig.__new__(ManuspectrumConfig)
        # Celery app stub WITH the task registered.
        fake_celery_app = SimpleNamespace(
            tasks={"manuspectrum.index_resources": object()}
        )
        fake_celery_module = SimpleNamespace(app=fake_celery_app)

        original_modules = sys.modules.copy()
        sys.modules["manuspectrum.celery"] = fake_celery_module  # type: ignore[assignment]
        try:
            with patch.object(apps_module, "settings") as mock_settings:
                mock_settings.BIBLISSIMA_ASYNC_INDEXING = True
                ManuspectrumConfig._check_async_indexing_config(config)

            self.assertTrue(mock_settings.BIBLISSIMA_ASYNC_INDEXING)
        finally:
            sys.modules.pop("manuspectrum.celery", None)
            if "manuspectrum.celery" in original_modules:
                sys.modules["manuspectrum.celery"] = original_modules[
                    "manuspectrum.celery"
                ]

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=True)
    def test_celery_import_error_disables_flag_and_logs_error(self):
        """An exception while importing Celery must disable async indexing
        and log an error (not propagate the exception)."""
        import sys
        import manuspectrum.apps as apps_module
        from manuspectrum.apps import ManuspectrumConfig

        config = ManuspectrumConfig.__new__(ManuspectrumConfig)

        # Force the celery import to fail.
        sys.modules["manuspectrum.celery"] = None  # type: ignore[assignment]
        try:
            with patch.object(apps_module, "settings") as mock_settings:
                mock_settings.BIBLISSIMA_ASYNC_INDEXING = True

                with self.assertLogs("manuspectrum.apps", level="ERROR") as cm:
                    ManuspectrumConfig._check_async_indexing_config(config)

            self.assertFalse(mock_settings.BIBLISSIMA_ASYNC_INDEXING)
            self.assertTrue(len(cm.output) >= 1)
        finally:
            del sys.modules["manuspectrum.celery"]
            # Restore from original import if cached.
            try:
                import importlib
                importlib.import_module("manuspectrum.celery")
            except Exception:
                pass


# ===========================================================================
# Integration smoke: _defer_indexing tx_id matches index_resources_async sig
# ===========================================================================


class DeferIndexingSignatureConsistencyTests(TestCase):
    """Verify that _defer_indexing's .delay() kwargs match index_resources_async
    signature — catching any future parameter rename."""

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=True)
    def test_tx_id_kwarg_is_transaction_id(self):
        """When a tx_id is given, .delay must receive transaction_id=<str>."""
        view = _make_view()
        tx_id = uuid.uuid4()

        with patch(PATCH_TASK) as mock_task:
            mock_task.delay.return_value = MagicMock()
            with self.captureOnCommitCallbacks(execute=True):
                view._defer_indexing(tx_id=tx_id)

        mock_task.delay.assert_called_once()
        _, kwargs = mock_task.delay.call_args
        self.assertEqual(kwargs.get("transaction_id"), str(tx_id))
        self.assertNotIn("resource_ids", kwargs)

    @override_settings(BIBLISSIMA_ASYNC_INDEXING=True)
    def test_resource_ids_kwarg_is_list_of_strings(self):
        """When resource_ids are given, .delay must receive resource_ids=[str, ...]."""
        view = _make_view()
        rid = uuid.uuid4()

        with patch(PATCH_TASK) as mock_task:
            mock_task.delay.return_value = MagicMock()
            with self.captureOnCommitCallbacks(execute=True):
                view._defer_indexing(resource_ids=[rid])

        mock_task.delay.assert_called_once()
        _, kwargs = mock_task.delay.call_args
        self.assertEqual(kwargs.get("resource_ids"), [str(rid)])
        self.assertNotIn("transaction_id", kwargs)
