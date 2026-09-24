"""What the Explorer shows to whom, decided once by ``visible_set``.

Usage:
    python manage.py test tests.test_explorer_visibility --settings="tests.test_settings"
"""

from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.cache import cache
from django.test import TestCase

from arches.app.models.models import NodeGroup, ResourceInstance
from arches.app.utils.permission_backend import assign_perm

from manuspectrum.utils.public_visibility import (
    draft_state_id_set,
    is_connected,
    reader_scope,
    visible_set,
)
from manuspectrum.views.iiif_annotation import IIIFAnnotationCollectionView
from tests.explorer_fixtures import ACTIVE, ExplorerCase

DEFAULT_LIFECYCLE_DRAFT = "9375c9a7-dad2-4f14-a5c1-d7e329fdde4f"
DEFAULT_LIFECYCLE_ACTIVE = "f75bb034-36e3-4ab4-8167-f520cf0b4c58"


class ReaderTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_the_anonymous_row_is_not_connected(self):
        anonymous = User.objects.get(username="anonymous")

        self.assertTrue(anonymous.is_authenticated)
        self.assertFalse(is_connected(anonymous))
        self.assertEqual(reader_scope(anonymous), "anonymous")

    def test_django_anonymous_user_is_not_connected(self):
        self.assertFalse(is_connected(AnonymousUser()))
        self.assertEqual(reader_scope(AnonymousUser()), "anonymous")

    def test_a_signed_in_editor_is_connected_and_keyed_by_id(self):
        editor = User.objects.create_user("explorer_editor", password="pw")
        editor.groups.add(Group.objects.get(name="Resource Editor"))

        self.assertTrue(is_connected(editor))
        self.assertEqual(reader_scope(editor), str(editor.pk))

    def test_the_initial_state_of_the_default_lifecycle_is_a_draft(self):
        drafts = draft_state_id_set()

        self.assertIn(DEFAULT_LIFECYCLE_DRAFT, drafts)
        self.assertNotIn(DEFAULT_LIFECYCLE_ACTIVE, drafts)


class VisibleSetTests(ExplorerCase):
    def ids(self, **named):
        return {str(r.pk) for r in named.values()}

    def test_every_open_chain_is_visible_to_the_visitor(self):
        vs = visible_set(self.anonymous)

        self.assertIn(str(self.documents["open"].pk), vs.documents)
        self.assertIn(str(self.components["open"].pk), vs.components)
        self.assertLessEqual(
            self.ids(a=self.analyses["open"], b=self.analyses["on_document"]),
            vs.analyses,
        )
        self.assertIn(str(self.samples["s1"].pk), vs.samples)
        self.assertIn(str(self.characterization.pk), vs.characterizations)

    def test_an_embargoed_document_hides_its_component_and_analyses(self):
        self.embargo(self.documents["embargoed"])

        vs = visible_set(self.anonymous)

        self.assertNotIn(str(self.documents["embargoed"].pk), vs.ids)
        self.assertNotIn(str(self.components["embargoed"].pk), vs.ids)
        self.assertNotIn(str(self.analyses["embargoed"].pk), vs.ids)

    def test_an_embargoed_project_hides_its_analyses_only(self):
        self.embargo(self.projects["side"])

        vs = visible_set(self.anonymous)

        self.assertNotIn(str(self.analyses["on_document"].pk), vs.analyses)
        self.assertIn(str(self.analyses["open"].pk), vs.analyses)

    def test_a_draft_project_hides_its_analyses_from_the_visitor_not_from_the_editor(
        self,
    ):
        self.make_draft(self.projects["side"])

        self.assertNotIn(
            str(self.analyses["on_document"].pk), visible_set(self.anonymous).analyses
        )
        editor = visible_set(self.editor)
        self.assertIn(str(self.analyses["on_document"].pk), editor.analyses)
        self.assertIn(str(self.analyses["on_document"].pk), editor.unpublished)

    def test_a_draft_analysis_is_kept_for_the_editor_and_marked(self):
        draft = str(self.analyses["draft"].pk)

        self.assertNotIn(draft, visible_set(self.anonymous).analyses)
        self.assertIn(draft, visible_set(self.editor).unpublished)

    def test_a_resource_in_the_initial_state_is_hidden_from_the_visitor(self):
        stray = ResourceInstance.objects.create(graph=self.graphs["document"])

        self.assertNotEqual(str(stray.resource_instance_lifecycle_state_id), ACTIVE)
        self.assertNotIn(str(stray.pk), visible_set(self.anonymous).documents)

    def test_an_unreadable_relation_nodegroup_breaks_the_chain(self):
        nodegroup = NodeGroup.objects.get(
            pk=self.nodes[("analysis", "component_observed")].nodegroup_id
        )
        with self.captureOnCommitCallbacks(execute=True):
            assign_perm("no_access_to_nodegroup", self.anonymous, nodegroup)

        reader = User.objects.get(pk=self.anonymous.pk)
        self.assertNotIn(str(self.analyses["open"].pk), visible_set(reader).analyses)

    def hide_project_links(self):
        nodegroup = NodeGroup.objects.get(
            pk=self.nodes[("analysis", "analysis_by_project")].nodegroup_id
        )
        with self.captureOnCommitCallbacks(execute=True):
            assign_perm("no_access_to_nodegroup", self.anonymous, nodegroup)
        return User.objects.get(pk=self.anonymous.pk)

    def test_an_unreadable_project_link_still_hides_the_analysis_of_an_embargoed_project(
        self,
    ):
        self.embargo(self.projects["side"])
        reader = self.hide_project_links()

        self.assertNotIn(
            str(self.analyses["on_document"].pk), visible_set(reader).analyses
        )

    def test_an_unreadable_project_link_still_hides_the_analysis_of_a_draft_project(
        self,
    ):
        self.make_draft(self.projects["side"])
        reader = self.hide_project_links()

        self.assertNotIn(
            str(self.analyses["on_document"].pk), visible_set(reader).analyses
        )

    def test_an_identification_whose_evidence_is_all_hidden_is_hidden(self):
        self.embargo(self.analyses["open"])
        self.embargo(self.analyses["on_document"])

        self.assertNotIn(
            str(self.characterization.pk), visible_set(self.anonymous).characterizations
        )

    def test_the_evidence_list_keeps_only_visible_analyses(self):
        self.embargo(self.analyses["open"])

        vs = visible_set(self.anonymous)

        self.assertEqual(
            vs.evidence[str(self.characterization.pk)],
            (str(self.analyses["on_document"].pk),),
        )

    def test_a_dangling_project_link_hides_nothing(self):
        self.tile(
            self.analyses["open"],
            "analysis_by_project",
            [{"resourceId": "00000000-0000-4000-8000-000000000000"}],
        )

        self.assertIn(
            str(self.analyses["open"].pk), visible_set(self.anonymous).analyses
        )

    def test_the_visible_set_follows_a_grant_on_commit(self):
        self.assertIn(
            str(self.analyses["open"].pk), visible_set(self.anonymous).analyses
        )

        self.embargo(self.analyses["open"])

        self.assertNotIn(
            str(self.analyses["open"].pk), visible_set(self.anonymous).analyses
        )


class CollectionUnderVisibleSetTests(ExplorerCase):
    def readable(self, user, document):
        analyses, public = IIIFAnnotationCollectionView()._readable_analyses(
            user, document
        )
        return {str(a.pk) for a in analyses}, public

    def test_a_hidden_project_takes_its_analysis_out_of_the_collection(self):
        self.embargo(self.projects["side"])

        reached, public = self.readable(self.anonymous, self.documents["open"])

        self.assertNotIn(str(self.analyses["on_document"].pk), reached)
        self.assertIn(str(self.analyses["open"].pk), reached)
        self.assertFalse(public)

    def test_a_draft_analysis_is_not_served_to_the_visitor(self):
        reached, public = self.readable(self.anonymous, self.documents["open"])

        self.assertNotIn(str(self.analyses["draft"].pk), reached)
        self.assertFalse(public)
