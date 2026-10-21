"""The project permission framework: restricted ids without a leaked scroll.

Runs against the test Elasticsearch index. ``get_restricted_instances`` is the
call behind every vector tile; the core one leaves a scroll context open each
time, the project subclass leaves none.

Usage:
    python manage.py test tests.test_permission_framework --settings="tests.test_settings"
"""

import uuid
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from arches.app.models.system_settings import settings as arches_settings
from arches.app.permissions.arches_default_allow import (
    ArchesDefaultAllowPermissionFramework,
)
from arches.app.search.mappings import RESOURCES_INDEX
from arches.app.search.search_engine_factory import SearchEngineInstance
from arches.app.utils import permission_backend

from manuspectrum.permissions.default_allow import (
    ManuSpectrumDefaultAllowPermissionFramework,
)


def scroll_searches(spy):
    """The calls of a spied ``search`` that opened a scroll context."""
    return [c for c in spy.call_args_list if c.kwargs.get("scroll")]


class RestrictedInstancesTests(TestCase):
    def setUp(self):
        self.se = SearchEngineInstance
        self.index = self.se._add_prefix(index=RESOURCES_INDEX)["index"]
        self.user = User.objects.create_user("restricted_reader", password="pw")
        self.other = User.objects.create_user("other_reader", password="pw")
        self.framework = ManuSpectrumDefaultAllowPermissionFramework()
        self.created = []
        self.addCleanup(self.remove_documents)

    def remove_documents(self):
        for resource_id in self.created:
            self.se.es.options(ignore_status=404).delete(
                index=self.index, id=resource_id, refresh=True
            )

    def index_resource(self, *blocked_users):
        resource_id = str(uuid.uuid4())
        self.se.es.index(
            index=self.index,
            id=resource_id,
            document={
                "permissions": [
                    {"users_with_no_access": [str(user.id) for user in blocked_users]}
                ]
            },
            refresh=True,
        )
        self.created.append(resource_id)
        return resource_id

    def restricted_for_user(self):
        mine = {self.index_resource(self.user) for _ in range(3)}
        self.index_resource(self.other)
        self.index_resource()
        return mine

    def test_the_setting_selects_the_project_framework(self):
        permission_backend._PERMISSION_FRAMEWORK = None
        self.addCleanup(setattr, permission_backend, "_PERMISSION_FRAMEWORK", None)

        self.assertIs(
            type(permission_backend._get_permission_framework()),
            ManuSpectrumDefaultAllowPermissionFramework,
        )

    def test_a_reader_gets_the_ids_the_core_method_returns(self):
        mine = self.restricted_for_user()

        core = ArchesDefaultAllowPermissionFramework.get_restricted_instances(
            self.framework, self.user, self.se
        )
        project = self.framework.get_restricted_instances(self.user, self.se)

        self.assertEqual(set(project), mine)
        self.assertEqual(set(core), set(project))

    def test_the_resources_filter_narrows_the_ids(self):
        mine = sorted(self.restricted_for_user())

        ids = self.framework.get_restricted_instances(
            self.user, self.se, resources=mine[:2]
        )

        self.assertEqual(set(ids), set(mine[:2]))

    def test_a_superuser_has_no_restricted_instance(self):
        self.restricted_for_user()
        self.user.is_superuser = True

        self.assertEqual(
            self.framework.get_restricted_instances(self.user, self.se), []
        )

    def test_a_result_that_fits_one_page_opens_no_scroll_context(self):
        self.restricted_for_user()

        with mock.patch.object(self.se, "search", wraps=self.se.search) as search:
            for _ in range(5):
                self.framework.get_restricted_instances(self.user, self.se)

        self.assertEqual(search.call_count, 5)
        self.assertEqual(scroll_searches(search), [])

    def test_the_core_method_opens_a_scroll_context_it_never_clears(self):
        self.restricted_for_user()

        with (
            mock.patch.object(self.se, "search", wraps=self.se.search) as search,
            mock.patch.object(
                self.se.es, "clear_scroll", wraps=self.se.es.clear_scroll
            ) as clear,
        ):
            for _ in range(5):
                ArchesDefaultAllowPermissionFramework.get_restricted_instances(
                    self.framework, self.user, self.se
                )

        self.assertEqual(len(scroll_searches(search)), 5)
        clear.assert_not_called()

    def test_beyond_the_limit_every_id_comes_back_and_the_scroll_is_cleared(self):
        mine = {self.index_resource(self.user) for _ in range(7)}

        with mock.patch.object(arches_settings, "SEARCH_RESULT_LIMIT", 3):
            with (
                mock.patch.object(self.se, "search", wraps=self.se.search) as search,
                mock.patch.object(
                    self.se.es, "clear_scroll", wraps=self.se.es.clear_scroll
                ) as clear,
            ):
                ids = self.framework.get_restricted_instances(self.user, self.se)

        self.assertEqual(sorted(ids), sorted(mine))
        self.assertEqual(len(scroll_searches(search)), 1)
        clear.assert_called_once()

    def test_the_scroll_is_cleared_when_a_page_fails(self):
        for _ in range(4):
            self.index_resource(self.user)

        with mock.patch.object(arches_settings, "SEARCH_RESULT_LIMIT", 2):
            with (
                mock.patch.object(
                    self.se.es, "clear_scroll", wraps=self.se.es.clear_scroll
                ) as clear,
                mock.patch.object(
                    self.se.es, "scroll", side_effect=RuntimeError("boom")
                ),
            ):
                with self.assertRaises(RuntimeError):
                    self.framework.get_restricted_instances(self.user, self.se)

        clear.assert_called_once()
