"""The reviewer's actions on a measurement-files run, and their undo.

``apply_action`` changes the prepared items of a run in state ``review`` and
writes exactly one ``MeasurementDecision`` whose ``before`` holds, per changed
item, the value of every field an action may touch (plus the dictionary
entries for ``validate_codes``); ``undo_last`` puts those values back and
deletes the row. Nothing is written to the database of resources here.

The Analysis an item goes to is ``chosen_analysis_id`` when set, else
``proposed_analysis_id``. An item the matcher or the run settled for good
(``TERMINAL_CAUSES``: already in the database, not a measurement, a lab CSV, a
CSV that breaks the contract) and an item that did not reach ``prepared`` are
skipped by every action. A partner of a CSV/raw pair follows the item acted on
(analysis, cause, decision). An action that changes nothing writes no row.
"""

import uuid

from django.db import transaction
from django.utils import timezone

from manuspectrum.constants.measurement_files import COMMON_CODES
from manuspectrum.constants.xy_presets import XY_PRESETS
from manuspectrum.measurement_files import matching, prepare
from manuspectrum.models import (
    MeasurementDecision,
    MeasurementItem,
    MeasurementNameCode,
    MeasurementRun,
    RendererConfig,
)

ACTIONS = (
    "assign",
    "validate",
    "set_aside",
    "restore_proposal",
    "apply_display",
    "add_anyway",
    "keep_replicas",
    "raw_only",
    "validate_codes",
)
FIELDS = (
    "chosen_analysis_id",
    "proposed_analysis_id",
    "cause",
    "decision",
    "display_config_id",
    "display_source",
    "outcome",
    "reason",
    "tokens",
)
TERMINAL_CAUSES = frozenset(
    {"in_database", "not_measure", "lab_csv_set_aside", "csv_contract"}
)
VALIDATE_CAUSES = frozenset({"near_name", "content_vs_display", "no_display"})
REPLICA_CAUSES = frozenset({"same_target", "name_alert"})
RAW_CLEARED_CAUSES = frozenset(
    {
        "format_vs_technique",
        "unreadable_raw",
        "too_large",
        "content_vs_display",
        "no_display",
    }
)
DISPLAY_CAUSES = frozenset({"no_display", "content_vs_display"})
REREAD_CAUSES = frozenset(
    {"unknown_codes", "no_analysis", "near_name", "format_vs_technique"}
)
KEPT_RAW = "kept_raw"
FAMILIES = frozenset(
    {matching.family_of(key) for key in XY_PRESETS} | set(COMMON_CODES.values())
)
MAX_CODES = 500
CODE_MAX_LENGTH = 32

CAUSE_ACTIONS = {
    "already_provided": ("add_anyway", "set_aside"),
    "same_target": ("keep_replicas", "assign", "set_aside"),
    "unknown_codes": ("validate_codes", "set_aside"),
    "name_alert": ("set_aside", "keep_replicas"),
    "near_name": ("validate", "assign"),
    "format_vs_technique": ("assign", "apply_display", "raw_only"),
    "no_display": ("apply_display",),
    "content_vs_display": ("apply_display", "validate"),
    "other_shelfmark": ("assign", "set_aside"),
    "no_analysis": ("assign", "set_aside"),
    "unreadable_raw": ("raw_only", "set_aside"),
    "too_large": ("raw_only", "set_aside"),
}
"""Actions the screen offers for each cause; terminal causes offer none."""


class ActionError(Exception):
    """A refused request: *reason* is the code the API answers with."""

    def __init__(self, reason, status=400):
        super().__init__(reason)
        self.reason, self.status = reason, status


class Skip(Exception):
    """An item an action does not apply to; *reason* goes in the answer."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def effective_analysis(item):
    return item.chosen_analysis_id or item.proposed_analysis_id


def ready_to_write(run):
    """True when no prepared item of *run* still waits for a decision."""
    return not run.items.filter(state="prepared", decision="pending").exists()


def _snapshot(item):
    out = {}
    for field in FIELDS:
        value = getattr(item, field)
        out[field] = str(value) if hasattr(value, "hex") else value
    return out


def _restore(item, values):
    for field, value in values.items():
        setattr(item, field, value)
    item.save(update_fields=list(values))


def _settle(item):
    """Give an item that is not set aside its ``ready``/``pending`` decision; no Analysis means cause ``no_analysis``."""
    if item.decision != "aside":
        if not effective_analysis(item) and not item.cause:
            item.cause = "no_analysis"
        prepare.settle(item)


def _decide(item, resolves):
    """Record the outcome of an action that settles the causes in *resolves*.

    The cause stays on the item (it says why a decision was needed). When the
    item carries no cause or one of *resolves*, it becomes ``ready`` if it has
    an Analysis and something to write, else ``pending``; another cause leaves
    it as it was (a set-aside item comes back as ``pending``).
    """
    _reopen(item)
    if not effective_analysis(item) and not item.cause:
        item.cause = "no_analysis"
    if not item.cause or item.cause in resolves:
        ok = effective_analysis(item) and prepare.has_something_to_write(item)
        item.decision = "ready" if ok else "pending"


def _reopen(item):
    if item.decision == "aside":
        item.decision = "pending"


def _run_wide_causes(ctx, item):
    """``already_provided`` and ``same_target`` for an item that just got an Analysis.

    Peers uploaded to the same Analysis that are not decided yet are flagged
    ``same_target`` with it.
    """
    target = effective_analysis(item)
    if not target or item.cause not in prepare.SOFT_CAUSES:
        return
    card = ctx.cards.get(str(target))
    if prepare._already_provided(item, card):
        item.cause = "already_provided"
        return
    if item.origin != "upload":
        return
    peers = [
        other
        for other in ctx.items()
        if other.pk != item.pk
        and other.origin == "upload"
        and other.decision != "aside"
        and not other.paired_item_id
        and str(effective_analysis(other)) == str(target)
    ]
    if not peers:
        return
    item.cause = "same_target"
    for peer in peers:
        if peer.cause in prepare.SOFT_CAUSES:
            ctx.mark(peer)
            peer.cause = "same_target"
            prepare.settle(peer)


class Context:
    """Snapshot, dictionary and prepared items of a run for one action.

    ``mark`` records an item's values the first time the action touches it;
    those are the ``before`` of the decision.
    """

    def __init__(self, run, acted=()):
        self.run = run
        cards, self.shelfmark = prepare.load_snapshot(run)
        self.cards = {c.id: c for c in cards}
        self.card_list = cards
        self.by_pk = {str(i.pk): i for i in run.items.filter(state="prepared")}
        for item in acted:
            if item.state == "prepared":
                self.by_pk[str(item.pk)] = item
        self.originals = {}

    def items(self):
        return list(self.by_pk.values())

    def mark(self, item):
        self.originals.setdefault(str(item.pk), _snapshot(item))

    def card(self, item):
        return self.cards.get(str(effective_analysis(item)))

    def codes(self):
        return {
            c.code: c.family
            for c in MeasurementNameCode.objects.filter(user=self.run.user)
        }

    def changed(self):
        return [
            (pk, self.by_pk[pk])
            for pk, old in self.originals.items()
            if _snapshot(self.by_pk[pk]) != old
        ]


def _assign(ctx, item, params):
    if item.origin == "stored":
        raise Skip("fixed_analysis")
    if "analysis_id" not in params:
        raise ActionError("bad_request")
    wanted = params["analysis_id"]
    if wanted is None:
        item.decision, item.cause = "aside", "no_analysis"
        return
    card = ctx.cards.get(str(wanted))
    if card is None or not card.editable:
        raise ActionError("unknown_analysis")
    item.chosen_analysis_id = card.id
    _reopen(item)
    item.cause = ""
    prepare.apply_target(item, card)
    _run_wide_causes(ctx, item)
    _settle(item)


def _validate(ctx, item, params):
    if not effective_analysis(item):
        raise Skip("no_analysis")
    if item.cause and item.cause not in VALIDATE_CAUSES:
        raise Skip("not_validatable")
    _decide(item, VALIDATE_CAUSES)


def _set_aside(ctx, item, params):
    item.decision = "aside"


def _restore_proposal(ctx, item, params):
    if item.paired_item_id:
        raise Skip("paired")
    if item.reason == KEPT_RAW:
        raise Skip("raw_only_kept")
    _reread(ctx, item)


def _apply_display(ctx, item, params):
    if item.outcome != "csv":
        raise Skip("no_csv")
    card = ctx.card(item)
    if "technique" in params:
        config_id, source, cause = prepare._display(card, None)
    elif "config_id" in params:
        config_id, source, cause = params["config_id"], "chosen", None
    elif "none" in params:
        config_id, source, cause = None, "none", None
    else:
        raise ActionError("bad_request")
    item.display_config_id, item.display_source = config_id, source
    _decide(item, set() if cause else DISPLAY_CAUSES | {"format_vs_technique"})


def _add_anyway(ctx, item, params):
    if item.cause != "already_provided":
        raise Skip("not_already_provided")
    _decide(item, {"already_provided"})


def _keep_replicas(ctx, item, params):
    if item.cause not in REPLICA_CAUSES:
        raise Skip("not_replicas")
    if not effective_analysis(item):
        raise Skip("no_analysis")
    _decide(item, REPLICA_CAUSES)


def _raw_only(ctx, item, params):
    if item.paired_item_id:
        raise Skip("paired")
    if item.origin == "stored":
        raise Skip("nothing_to_write")
    item.outcome, item.reason = "raw_only", KEPT_RAW
    item.display_config_id, item.display_source = None, "none"
    _decide(item, RAW_CLEARED_CAUSES)


HANDLERS = {
    "assign": _assign,
    "validate": _validate,
    "set_aside": _set_aside,
    "restore_proposal": _restore_proposal,
    "apply_display": _apply_display,
    "add_anyway": _add_anyway,
    "keep_replicas": _keep_replicas,
    "raw_only": _raw_only,
}


def _reread(ctx, item):
    """Read the name again and propose from scratch (what ``prepare`` did), with no conversion."""
    item.chosen_analysis_id = None
    item.decision, item.cause = "pending", ""
    item.display_config_id, item.display_source = None, "none"
    codes = ctx.codes()
    prepare.propose_item(
        item,
        ctx.card_list,
        codes,
        ctx.shelfmark,
        item.content_preset or None,
        {},
    )
    if item.decision != "aside":
        _run_wide_causes(ctx, item)
        if (
            item.outcome in prepare.UNCONVERTED
            and not item.paired_item_id
            and not item.cause
        ):
            item.cause = "unreadable_raw"
        _settle(item)


def _sync_partner(ctx, item):
    partner = ctx.by_pk.get(str(item.paired_item_id))
    if partner is None:
        return
    ctx.mark(partner)
    partner.chosen_analysis_id = item.chosen_analysis_id
    partner.proposed_analysis_id = item.proposed_analysis_id
    partner.cause, partner.decision = item.cause, item.decision


def _lock(run_id):
    run = MeasurementRun.objects.select_for_update().get(pk=run_id)
    if run.state != "review":
        raise ActionError("run_not_in_review", 409)
    return run


def clean_code(code):
    return (
        isinstance(code, str)
        and 0 < len(code.strip()) <= CODE_MAX_LENGTH
        and not any(c.isspace() for c in code.strip())
    )


def clean_family(family):
    return family == matching.IGNORE or family in FAMILIES


def write_codes(user, mapping):
    """Upsert the user's dictionary entries; returns ``{code: previous family or None}`` for those that changed.

    Codes are unique per user whatever their case; the case first written is kept.
    """
    before, now = {}, timezone.now()
    for code, family in mapping.items():
        row = MeasurementNameCode.objects.filter(user=user, code__iexact=code).first()
        if row is None:
            if MeasurementNameCode.objects.filter(user=user).count() >= MAX_CODES:
                raise ActionError("too_many_codes", 409)
            MeasurementNameCode.objects.create(
                user=user, code=code, family=family, last_used_at=now
            )
            before[code] = None
        else:
            if row.family != family:
                before[row.code] = row.family
            row.family, row.last_used_at = family, now
            row.save(update_fields=["family", "last_used_at"])
    return before


def _validate_codes(ctx, params):
    if not isinstance(params, dict) or not params:
        raise ActionError("bad_request")
    mapping = {}
    for code, family in params.items():
        if not clean_code(code):
            raise ActionError("bad_code")
        if not clean_family(family):
            raise ActionError("bad_family")
        mapping[code.strip()] = family
    before_codes = write_codes(ctx.run.user, mapping)
    for item in ctx.items():
        if (
            item.decision == "pending"
            and item.cause in REREAD_CAUSES
            and not item.chosen_analysis_id
            and not item.paired_item_id
            and item.reason != KEPT_RAW
        ):
            ctx.mark(item)
            _reread(ctx, item)
    return before_codes


def _display_params(params):
    keys = [k for k in ("config_id", "technique", "none") if k in params]
    if len(keys) != 1:
        raise ActionError("bad_request")
    if keys[0] != "config_id":
        return {keys[0]: True}
    try:
        config_id = uuid.UUID(str(params["config_id"]))
    except ValueError:
        raise ActionError("bad_request")
    if not RendererConfig.objects.filter(pk=config_id).exists():
        raise ActionError("unknown_display")
    return {"config_id": config_id}


def apply_action(run_id, action, item_ids, params):
    """Run *action* on *item_ids* of a run in ``review``; returns ``{"changed", "skipped", "decision"}``.

    Raises ``ActionError`` for a refused request. The call is one
    transaction. ``validate_codes`` ignores *item_ids* (it re-reads every
    pending item the dictionary can unblock) and takes ``{code: family|ignore}``
    as *params*; the other actions take their parameters from *params*.
    """
    if action not in ACTIONS:
        raise ActionError("bad_action")
    if not isinstance(params, dict):
        raise ActionError("bad_request")
    skipped = []
    with transaction.atomic():
        run = _lock(run_id)
        before_codes = {}
        if action == "validate_codes":
            ctx = Context(run)
            before_codes = _validate_codes(ctx, params)
        else:
            if not isinstance(item_ids, list) or not item_ids:
                raise ActionError("bad_request")
            wanted = {str(i) for i in item_ids}
            found = list(
                MeasurementItem.objects.select_for_update().filter(
                    run=run, pk__in=wanted
                )
            )
            if {str(i.pk) for i in found} != wanted:
                raise ActionError("unknown_item", 404)
            if action == "apply_display":
                params = _display_params(params)
            ctx = Context(run, found)
            for item in sorted(found, key=lambda i: str(i.pk)):
                item_id = str(item.pk)
                if item.state != "prepared":
                    skipped.append({"id": item_id, "reason": "not_prepared"})
                    continue
                if item.cause in TERMINAL_CAUSES:
                    skipped.append({"id": item_id, "reason": "settled"})
                    continue
                ctx.mark(item)
                try:
                    HANDLERS[action](ctx, item, params)
                except Skip as skip:
                    skipped.append({"id": item_id, "reason": skip.reason})
                    continue
                if _snapshot(item) == ctx.originals[item_id]:
                    skipped.append({"id": item_id, "reason": "unchanged"})
                elif item.paired_item_id:
                    _sync_partner(ctx, item)
        changed = ctx.changed()
        if not changed and not before_codes:
            raise ActionError("nothing_changed", 422)
        for _, item in changed:
            item.save(update_fields=list(FIELDS))
        entry = {"items": {pk: ctx.originals[pk] for pk, _ in changed}}
        if before_codes:
            entry["codes"] = before_codes
        decision = MeasurementDecision.objects.create(
            run=run, action=action, before=entry
        )
    return {"changed": len(changed), "skipped": skipped, "decision": decision}


def undo_last(run_id):
    """Restore the newest decision's ``before`` and delete it; returns the action undone."""
    with transaction.atomic():
        run = _lock(run_id)
        decision = run.decisions.first()
        if decision is None:
            raise ActionError("nothing_to_undo", 409)
        for item_id, values in decision.before.get("items", {}).items():
            item = MeasurementItem.objects.filter(run=run, pk=item_id).first()
            if item is not None:
                _restore(item, values)
        for code, family in decision.before.get("codes", {}).items():
            rows = MeasurementNameCode.objects.filter(user=run.user, code__iexact=code)
            if family is None:
                rows.delete()
            else:
                rows.update(family=family)
        action = decision.action
        decision.delete()
    return action
