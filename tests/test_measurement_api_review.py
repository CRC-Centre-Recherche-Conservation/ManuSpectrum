import json
import uuid

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django.utils import translation

from manuspectrum.constants.measurement_files import CAUSES
from manuspectrum.constants.xy_presets import XY_PRESETS
from manuspectrum.measurement_files import decisions, staging
from manuspectrum.measurement_files.converters.base import UNREADABLE_LABELS
from manuspectrum.models import (
    MeasurementDecision,
    MeasurementItem,
    MeasurementNameCode,
    RendererConfig,
)
from tests import test_measurement_prepare as base
from tests.measurement_fixtures import elio_mca

counts = base.counts
ELIO = base.ELIO


class ReviewCase(base.PrepareCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.editor)

    def reviewed(self):
        self.prepare_all()
        self.assertEqual(self.run.state, "review")

    def url(self, name, **kw):
        return reverse(f"api-measurement-{name}", args=[self.run.id], **kw)

    def act(self, action, items, params=None, run_url=None):
        return self.client.post(
            run_url or self.url("decisions"),
            json.dumps(
                {
                    "action": action,
                    "item_ids": [str(i.id) for i in items],
                    "params": params or {},
                }
            ),
            content_type="application/json",
        )

    def undo(self):
        return self.client.post(self.url("decisions-undo"))

    def fields(self, item):
        item = self.item(item)
        return {f: getattr(item, f) for f in decisions.FIELDS}

    def changed_fields(self, before, item):
        after = self.fields(item)
        return {f for f in before if before[f] != after[f]}


class ActionTests(ReviewCase):
    def test_assign_changes_its_fields_and_logs_before(self):
        item = self.upload("Zz_f1r.mca", ELIO)
        self.reviewed()
        before = self.fields(item)
        self.assertEqual(self.item(item).cause, "no_analysis")
        response = self.act("assign", [item], {"analysis_id": self.target("xrf7")})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["changed"], 1)
        after = self.item(item)
        self.assertEqual(str(after.chosen_analysis_id), self.target("xrf7"))
        self.assertEqual((after.decision, after.cause), ("ready", ""))
        self.assertEqual(after.display_config_id, self.config("xrf"))
        self.assertEqual(
            self.changed_fields(before, item),
            {
                "chosen_analysis_id",
                "decision",
                "cause",
                "display_config_id",
                "display_source",
            },
        )
        row = MeasurementDecision.objects.get()
        self.assertEqual(row.action, "assign")
        self.assertEqual(row.before["items"][str(item.id)]["decision"], "pending")
        self.assertEqual(row.before["items"][str(item.id)]["cause"], "no_analysis")

    def test_assign_to_no_analysis_sets_the_file_aside(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        self.act("assign", [item], {"analysis_id": None})
        item = self.item(item)
        self.assertEqual((item.decision, item.cause), ("aside", "no_analysis"))

    def test_assign_refuses_an_unknown_analysis_and_changes_nothing(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        response = self.act("assign", [item], {"analysis_id": str(uuid.uuid4())})
        self.assertEqual(
            (response.status_code, response.json()["error"]),
            (400, "unknown_analysis"),
        )
        self.assertEqual(MeasurementDecision.objects.count(), 0)
        self.assertEqual(self.item(item).decision, "ready")

    def test_assign_to_an_analysis_with_the_same_format_is_already_provided(self):
        self.stored_file(self.targets["xrf9"], "old.MCA", elio_mca(counts(5)))
        item = self.upload("Zz_f1r.mca", ELIO)
        self.reviewed()
        self.act("assign", [item], {"analysis_id": self.target("xrf9")})
        item = self.item(item)
        self.assertEqual((item.decision, item.cause), ("pending", "already_provided"))

    def test_add_anyway_clears_already_provided(self):
        self.stored_file(self.targets["xrf9"], "old.MCA", elio_mca(counts(5)))
        item = self.upload("X9_f1r.mca", elio_mca(counts(9)))
        self.reviewed()
        before = self.fields(item)
        self.act("add_anyway", [item])
        self.assertEqual(
            (self.item(item).decision, self.item(item).cause),
            ("ready", "already_provided"),
        )
        self.assertEqual(self.changed_fields(before, item), {"decision"})

    def test_keep_replicas_settles_the_same_target_files(self):
        first = self.upload("X10_f1r.mca", elio_mca(counts(1)))
        second = self.upload("X10_f1r_bis.mca", elio_mca(counts(2)))
        self.reviewed()
        self.act("keep_replicas", [first, second])
        for item in (first, second):
            item = self.item(item)
            self.assertEqual((item.decision, item.cause), ("ready", "same_target"))
        self.assertEqual(len(MeasurementDecision.objects.get().before["items"]), 2)

    def test_validate_accepts_a_content_vs_display_proposal(self):
        item = self.upload("IR3_f1r.0", base.OPUS)
        self.reviewed()
        self.act("validate", [item])
        item = self.item(item)
        self.assertEqual((item.decision, item.cause), ("ready", "content_vs_display"))
        self.assertEqual(item.display_config_id, self.config("ftir"))

    def test_validate_skips_what_it_cannot_accept(self):
        item = self.upload("F2_f1r.0", base.OPUS)
        self.reviewed()
        response = self.act("validate", [item])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(MeasurementDecision.objects.count(), 0)

    def test_set_aside_touches_only_the_decision(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        before = self.fields(item)
        self.act("set_aside", [item])
        self.assertEqual(self.changed_fields(before, item), {"decision"})
        self.assertEqual(self.item(item).decision, "aside")

    def test_restore_proposal_reopens_a_file_set_aside(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        self.act("assign", [item], {"analysis_id": self.target("xrf8")})
        self.act("set_aside", [item])
        response = self.act("restore_proposal", [item])
        self.assertEqual(response.status_code, 200, response.content)
        item = self.item(item)
        self.assertIsNone(item.chosen_analysis_id)
        self.assertEqual(str(item.proposed_analysis_id), self.target("xrf7"))
        self.assertEqual((item.decision, item.cause), ("ready", ""))

    def test_apply_display_by_configuration_technique_and_none(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        config = RendererConfig.objects.create(
            rendererid=uuid.uuid4(), name="Custom XRF", config={}
        )
        before = self.fields(item)
        self.act("apply_display", [item], {"config_id": str(config.pk)})
        item = self.item(item)
        self.assertEqual(
            (item.display_config_id, item.display_source), (config.pk, "chosen")
        )
        self.assertEqual(
            self.changed_fields(before, item), {"display_config_id", "display_source"}
        )
        self.act("apply_display", [item], {"none": True})
        item = self.item(item)
        self.assertEqual((item.display_config_id, item.display_source), (None, "none"))
        self.act("apply_display", [item], {"technique": True})
        item = self.item(item)
        self.assertEqual(
            (item.display_config_id, item.display_source),
            (self.config("xrf"), "technique"),
        )

    def test_apply_display_refuses_an_unknown_configuration(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        response = self.act("apply_display", [item], {"config_id": str(uuid.uuid4())})
        self.assertEqual(response.json()["error"], "unknown_display")

    def test_apply_display_clears_content_vs_display(self):
        item = self.upload("IR3_f1r.0", base.OPUS)
        self.reviewed()
        self.act(
            "apply_display", [item], {"config_id": str(self.config("ftir_reflection"))}
        )
        item = self.item(item)
        self.assertEqual((item.decision, item.cause), ("ready", "content_vs_display"))

    def test_raw_only_keeps_the_raw_file_alone(self):
        item = self.upload("X7_f1r.mca", elio_mca([1]))
        self.reviewed()
        self.assertEqual(self.item(item).cause, "unreadable_raw")
        before = self.fields(item)
        self.act("assign", [item], {"analysis_id": self.target("xrf7")})
        self.act("raw_only", [item])
        item = self.item(item)
        self.assertEqual((item.outcome, item.reason), ("raw_only", "kept_raw"))
        self.assertEqual((item.decision, item.cause), ("ready", ""))
        self.assertEqual(item.display_source, "none")
        self.assertEqual(
            self.changed_fields(before, item),
            {"chosen_analysis_id", "outcome", "reason", "decision", "cause"},
        )

    def test_each_action_writes_exactly_one_row(self):
        item = self.upload("X7_f1r.mca", ELIO)
        other = self.upload("X8_f1r.mca", base.ELIO_NO_CAL)
        self.reviewed()
        self.act("set_aside", [item, other])
        self.assertEqual(MeasurementDecision.objects.count(), 1)
        self.act("restore_proposal", [item, other])
        self.assertEqual(MeasurementDecision.objects.count(), 2)

    def test_a_settled_file_is_skipped(self):
        self.stored_file(self.targets["xrf9"], "old.mca", base.ELIO)
        item = self.upload("X9_f1r.mca", base.ELIO)
        ok = self.upload("X7_f1r.mca", elio_mca(counts(4)))
        self.reviewed()
        response = self.act("set_aside", [item, ok])
        body = response.json()
        self.assertEqual(body["changed"], 1)
        self.assertEqual(body["skipped"], [{"id": str(item.id), "reason": "settled"}])

    def test_a_pair_follows_the_item_acted_on(self):
        raw = self.upload("X7_f1r.mca", elio_mca([1]))
        csv = self.upload("X7_f1r.csv", (base.CONTRACT / "xrf.csv").read_bytes())
        self.reviewed()
        self.assertEqual(self.item(csv).paired_item_id, raw.id)
        self.act("set_aside", [csv])
        self.assertEqual(self.item(raw).decision, "aside")
        self.undo()
        self.assertNotEqual(self.item(raw).decision, "aside")

    def test_the_items_must_belong_to_the_run(self):
        self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        stranger = MeasurementItem(id=uuid.uuid4())
        response = self.act("set_aside", [stranger])
        self.assertEqual(response.status_code, 404)

    def test_bad_requests(self):
        self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        self.assertEqual(self.act("explode", []).status_code, 400)
        self.assertEqual(self.act("set_aside", []).status_code, 400)


class ReviewStateTests(ReviewCase):
    def test_actions_and_undo_are_refused_outside_review(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        self.run.state = "writing"
        self.run.save()
        response = self.act("set_aside", [item])
        self.assertEqual(
            (response.status_code, response.json()["error"]),
            (409, "run_not_in_review"),
        )
        self.assertEqual(self.undo().status_code, 409)
        response = self.act("validate_codes", [], {"Xq": "xrf"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.item(item).decision, "ready")
        self.assertFalse(MeasurementNameCode.objects.exists())


class UndoTests(ReviewCase):
    def test_undo_restores_the_last_action_and_deletes_its_row(self):
        item = self.upload("Zz_f1r.mca", ELIO)
        self.reviewed()
        original = self.fields(item)
        self.act("assign", [item], {"analysis_id": self.target("xrf7")})
        self.act("set_aside", [item])
        response = self.undo()
        self.assertEqual(response.json()["undone"], "set_aside")
        self.assertEqual(self.item(item).decision, "ready")
        self.assertEqual(MeasurementDecision.objects.count(), 1)
        self.undo()
        self.assertEqual(self.fields(item), original)
        self.assertEqual(MeasurementDecision.objects.count(), 0)
        self.assertEqual(self.undo().status_code, 409)

    def test_undo_of_a_display_change(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        original = self.fields(item)
        self.act("apply_display", [item], {"none": True})
        self.undo()
        self.assertEqual(self.fields(item), original)


class DictionaryTests(ReviewCase):
    def codes(self):
        return self.client.get(reverse("api-measurement-codes")).json()

    def test_crud_is_case_insensitive_and_per_user(self):
        url = reverse("api-measurement-codes")
        post = lambda payload: self.client.post(
            url, json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(post({"code": "Ffsc", "family": "fors"}).status_code, 201)
        self.assertEqual(post({"code": "FFSC", "family": "ignore"}).status_code, 200)
        rows = self.codes()["codes"]
        self.assertEqual([(r["code"], r["family"]) for r in rows], [("Ffsc", "ignore")])
        self.assertEqual(post({"code": "x y", "family": "fors"}).status_code, 400)
        self.assertEqual(post({"code": "Zq", "family": "nonsense"}).status_code, 400)
        other = User.objects.create_user("dict_other", password="pw")
        other.groups.add(Group.objects.get(name="Resource Editor"))
        MeasurementNameCode.objects.create(user=other, code="Ffsc", family="xrf")
        self.assertEqual(len(self.codes()["codes"]), 1)
        self.assertEqual(self.client.delete(url + "?code=ffsc").status_code, 200)
        self.assertEqual(self.codes()["codes"], [])
        self.assertEqual(self.client.delete(url + "?code=ffsc").status_code, 404)
        self.assertTrue(MeasurementNameCode.objects.filter(user=other).exists())

    def test_validate_codes_reproposes_the_files_it_unblocks(self):
        item = self.upload("f1r_Xq8.mca", ELIO)
        other = self.upload("Zz_f1r.mca", base.ELIO_NO_CAL)
        self.reviewed()
        self.assertEqual(self.item(item).cause, "unknown_codes")
        before = {i.id: self.fields(i) for i in (item, other)}
        response = self.act("validate_codes", [], {"Xq": "xrf"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["changed"], 1)
        item = self.item(item)
        self.assertEqual(str(item.proposed_analysis_id), self.target("xrf8"))
        self.assertEqual((item.decision, item.cause), ("ready", ""))
        self.assertEqual(self.fields(other), before[other.id])
        self.assertEqual(
            MeasurementNameCode.objects.get(user=self.editor).family, "xrf"
        )
        self.undo()
        self.assertFalse(MeasurementNameCode.objects.exists())
        self.assertEqual(self.fields(item), before[item.id])

    def test_validate_codes_undo_restores_a_changed_family(self):
        MeasurementNameCode.objects.create(user=self.editor, code="Xq", family="fors")
        self.upload("f1r_Xq8.mca", ELIO)
        self.reviewed()
        self.act("validate_codes", [], {"xq": "xrf"})
        self.assertEqual(MeasurementNameCode.objects.get().family, "xrf")
        self.undo()
        self.assertEqual(MeasurementNameCode.objects.get().family, "fors")

    def test_a_dictionary_entry_is_used_by_the_next_prepare(self):
        MeasurementNameCode.objects.create(user=self.editor, code="Xq", family="xrf")
        item = self.upload("f1r_Xq8.mca", ELIO)
        self.reviewed()
        self.assertEqual(str(self.item(item).proposed_analysis_id), self.target("xrf8"))

    def test_validate_codes_refuses_a_bad_family(self):
        self.upload("f1r_Xq8.mca", ELIO)
        self.reviewed()
        self.assertEqual(
            self.act("validate_codes", [], {"Xq": "nope"}).status_code, 400
        )
        self.assertFalse(MeasurementNameCode.objects.exists())


class ReadingTests(ReviewCase):
    def prepared(self):
        self.upload("X7_f1r.mca", ELIO)
        self.upload("IR3_f1r.0", base.OPUS)
        self.upload("X10_f1r.mca", elio_mca(counts(1)))
        self.upload("X10_f1r_bis.mca", elio_mca(counts(2)))
        self.upload("Zz_f9v.mca", elio_mca(counts(8)))
        self.reviewed()

    def test_items_carry_analysis_technique_display_and_tokens(self):
        self.prepared()
        body = self.client.get(self.url("items")).json()
        self.assertEqual(body["total"], 5)
        self.assertFalse(body["ready_to_write"])
        row = next(r for r in body["items"] if r["name"] == "X7_f1r.mca")
        self.assertEqual(row["analysis"], {"id": self.target("xrf7"), "label": "X 7"})
        self.assertEqual(row["technique"]["preset"], "xrf")
        self.assertEqual(
            row["display"],
            {
                "config_id": XY_PRESETS["xrf"]["config_id"],
                "name": XY_PRESETS["xrf"]["name"],
                "source": "technique",
                "auto": True,
            },
        )
        self.assertTrue(row["tokens"])
        self.assertEqual(row["decision"], "ready")

    def test_items_filter_by_state_cause_and_search(self):
        self.prepared()
        get = lambda **q: self.client.get(self.url("items"), q).json()
        self.assertEqual(get(state="ready")["total"], 1)
        self.assertEqual(get(cause="same_target")["total"], 2)
        self.assertEqual(get(q="IR3")["total"], 1)
        self.assertEqual(get(q="x 7")["total"], 1)
        self.assertEqual(get(q="NOPE")["total"], 0)
        self.assertEqual(get(cause="same_target", q="bis")["total"], 1)
        self.assertEqual(
            self.client.get(self.url("items"), {"group": "x"}).status_code, 400
        )

    def test_items_group_and_page(self):
        self.prepared()
        body = self.client.get(self.url("items"), {"group": "state"}).json()
        groups = [r["group"] for r in body["items"]]
        self.assertEqual(groups, sorted(groups))
        self.assertEqual(set(groups), {"ready", "pending"})
        self.assertEqual(
            self.client.get(self.url("items"), {"page": 2}).json()["items"], []
        )

    def test_causes_are_sorted_by_count_with_labels_and_actions(self):
        self.prepared()
        rows = self.client.get(self.url("causes")).json()
        self.assertEqual(rows[0]["cause"], "same_target")
        self.assertEqual((rows[0]["pending"], rows[0]["settled"]), (2, 0))
        self.assertIn("keep_replicas", rows[0]["actions"])
        self.assertEqual(
            rows[0]["label"], "Several files target the same analysis and role."
        )
        pending = [r["pending"] for r in rows]
        self.assertEqual(pending, sorted(pending, reverse=True))

    def test_a_settled_cause_stays_listed_and_undo_makes_it_pending_again(self):
        first = self.upload("X10_f1r.mca", elio_mca(counts(1)))
        second = self.upload("X10_f1r_bis.mca", elio_mca(counts(2)))
        self.reviewed()
        self.act("keep_replicas", [first, second])
        rows = {r["cause"]: r for r in self.client.get(self.url("causes")).json()}
        self.assertEqual(
            (rows["same_target"]["pending"], rows["same_target"]["settled"]), (0, 2)
        )
        listed = self.client.get(self.url("items"), {"cause": "same_target"}).json()
        self.assertEqual(
            sorted(r["decision"] for r in listed["items"]), ["ready", "ready"]
        )
        self.undo()
        rows = {r["cause"]: r for r in self.client.get(self.url("causes")).json()}
        self.assertEqual(
            (rows["same_target"]["pending"], rows["same_target"]["settled"]), (2, 0)
        )

    def test_labels_follow_the_run_language(self):
        self.upload("X10_f1r.mca", elio_mca(counts(1)))
        self.upload("X10_f1r_bis.mca", elio_mca(counts(2)))
        self.run.language = "fr"
        self.run.save()
        self.reviewed()
        rows = self.client.get(self.url("causes")).json()
        self.assertEqual(
            rows[0]["label"],
            "Plusieurs fichiers visent la même analyse et le même rôle.",
        )

    def test_ready_to_write_when_nothing_is_pending(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        self.assertTrue(self.client.get(self.url("items")).json()["ready_to_write"])
        self.act("set_aside", [item])
        self.assertTrue(self.client.get(self.url("items")).json()["ready_to_write"])

    def test_last_action_is_reported(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        self.assertIsNone(self.client.get(self.url("items")).json()["last_action"])
        self.act("set_aside", [item])
        last = self.client.get(self.url("items")).json()["last_action"]
        self.assertEqual((last["action"], last["items"]), ("set_aside", 1))


class PickerTests(ReviewCase):
    def test_counts_filters_and_proposal(self):
        self.stored_file(self.targets["xrf9"], "old.mca", elio_mca(counts(5)))
        item = self.upload("X7_f1r.mca", ELIO)
        self.upload("X7_f1r_b.mca", elio_mca(counts(6)))
        self.reviewed()
        get = lambda **q: self.client.get(self.url("analyses"), q).json()
        cards = {c["name"]: c for c in get(item=str(item.id))["analyses"]}
        self.assertEqual(cards["X 7"]["receives"], 2)
        self.assertTrue(cards["X 7"]["proposed"])
        self.assertFalse(cards["X 8"]["proposed"])
        self.assertEqual(cards["X 9"]["already"], 1)
        self.assertEqual(cards["X 9"]["receives"], 0)
        self.assertTrue(cards["X 9"]["same_format"])
        self.assertFalse(cards["X 7"]["same_format"])
        technique = get(technique="ftir")
        self.assertEqual([c["name"] for c in technique["analyses"]], ["IR 3"])
        self.assertEqual(technique["hidden"], len(cards) - 1)
        folio = get(folio="1r")
        self.assertTrue(folio["analyses"])
        self.assertTrue(all("f1r" in c["folios"] for c in folio["analyses"]))
        self.assertEqual(len(folio["analyses"]) + folio["hidden"], len(cards))
        nothing = get(folio="f9z")
        self.assertEqual((nothing["analyses"], nothing["hidden"]), ([], len(cards)))
        self.assertEqual(get(q="x 1")["analyses"][0]["name"], "X 10")

    def test_the_picker_reads_the_snapshot_not_the_database(self):
        self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        from unittest import mock

        with mock.patch(
            "manuspectrum.measurement_files.catalogue.document_analyses",
            side_effect=AssertionError("database read"),
        ):
            body = self.client.get(self.url("analyses")).json()
        self.assertTrue(body["analyses"])

    def test_an_aside_file_does_not_count_as_received(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        self.act("set_aside", [item])
        cards = {
            c["name"]: c
            for c in self.client.get(self.url("analyses")).json()["analyses"]
        }
        self.assertEqual(cards["X 7"]["receives"], 0)


class PreviewTests(ReviewCase):
    def test_returns_the_csv_description_and_display(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        response = self.client.get(
            reverse("api-measurement-preview", args=[self.run.id, item.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])
        body = response.json()
        self.assertEqual(
            body["csv"], staging.read(self.run.id, f"{item.id}-converted.csv").decode()
        )
        self.assertEqual(set(body["description"]), {"en", "fr"})
        self.assertEqual(body["display"]["config_id"], XY_PRESETS["xrf"]["config_id"])
        self.assertEqual(body["display"]["source"], "technique")

    def test_a_raw_only_item_has_no_csv(self):
        item = self.upload("X7_f1r.mca", elio_mca([1]))
        self.reviewed()
        body = self.client.get(
            reverse("api-measurement-preview", args=[self.run.id, item.id])
        ).json()
        self.assertIsNone(body["csv"])
        self.assertIsNone(body["description"])

    def test_a_lone_csv_previews_its_own_text(self):
        data = (base.CONTRACT / "xrf.csv").read_bytes()
        item = self.upload("lone.csv", data)
        self.reviewed()
        body = self.client.get(
            reverse("api-measurement-preview", args=[self.run.id, item.id])
        ).json()
        self.assertEqual(body["csv"], data.decode())

    def test_another_user_gets_a_bodyless_404_everywhere(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        other = User.objects.create_user("review_other", password="pw")
        other.groups.add(Group.objects.get(name="Resource Editor"))
        self.client.force_login(other)
        for response in (
            self.client.get(
                reverse("api-measurement-preview", args=[self.run.id, item.id])
            ),
            self.client.get(self.url("items")),
            self.client.get(self.url("causes")),
            self.client.get(self.url("analyses")),
            self.act("set_aside", [item]),
            self.undo(),
        ):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.content, b"")
        self.assertEqual(self.item(item).decision, "ready")

    def test_a_user_outside_the_group_is_refused(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.reviewed()
        outsider = User.objects.create_user("review_plain", password="pw")
        self.client.force_login(outsider)
        response = self.client.get(
            reverse("api-measurement-preview", args=[self.run.id, item.id])
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.client.get(reverse("api-measurement-codes")).status_code, 403
        )


class CatalogueTests(ReviewCase):
    def test_every_cause_and_unreadable_code_has_a_french_translation(self):
        with translation.override("fr"):
            for table in (CAUSES, UNREADABLE_LABELS):
                for key, msgid in table.items():
                    text = translation.gettext(msgid)
                    self.assertNotEqual(text, msgid, key)

    def test_every_cause_with_actions_names_known_actions(self):
        for cause, actions in decisions.CAUSE_ACTIONS.items():
            self.assertIn(cause, CAUSES)
            self.assertTrue(set(actions) <= set(decisions.ACTIONS), cause)
