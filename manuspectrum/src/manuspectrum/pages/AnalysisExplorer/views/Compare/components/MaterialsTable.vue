<script setup lang="ts">
import { computed, ref } from "vue";
import { useGettext } from "vue3-gettext";

import CertaintyScale from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/CertaintyScale.vue";
import ElementLevels from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ElementLevels.vue";
import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";
import LinkedChip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LinkedChip.vue";
import MaterialEvidence from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/MaterialEvidence.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    colourNode,
    componentNode,
    materialNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import {
    bestConfidence,
    componentsOf,
    groupByComponent,
    groupByPair,
    materialCounts,
    shownRecords,
    unionCanvases,
    unionColours,
    unionComponents,
    unionEvidence,
    unionLevels,
    unionMaterials,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/materials.ts";
import { selectionSlots } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";

import type {
    AnalysisHit,
    Label,
    NamedRef,
    RankedValue,
    Ref,
    SynthesisCanvas,
    SynthesisPair,
    Technique,
    ValueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { MaterialsGrouping } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type {
    ElementLevel,
    GroupedRecords,
    MaterialGroup,
    MaterialRecord,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/materials.ts";

interface GroupingOption {
    value: MaterialsGrouping;
    label: string;
}

/** What the Selection column says of a line. */
interface SelectionCell {
    /** Slot tags (A1…) of a record of the Selection. */
    slots: string[];
    /** « cites A5, A7 » for a record citing the Selection; null otherwise. */
    cites: string | null;
    /** Records of the Selection and records citing it, for a group; null for a record. */
    counts: { selected: number; citing: number } | null;
}

/** A row of the table: a record, or a group (`open` when its records follow, `nested` under it). */
interface Row {
    kind: "record" | "group";
    key: string;
    node: NodeId;
    nested: boolean;
    open: boolean;
    name: Label;
    rest: string;
    /** A record's full name. */
    title: string | undefined;
    unpublished: boolean;
    certainty: RankedValue | null;
    best: boolean;
    colours: ValueRef[];
    components: Ref[];
    /** A component group's materials, in its Component column. */
    materials: string;
    folios: string;
    levels: ElementLevel[];
    evidence: NamedRef[];
    selection: SelectionCell;
}

const GROUPINGS: readonly MaterialsGrouping[] = ["record", "pair", "component"];

/**
 * The Materials window of Compare: one table of every identified material
 * of the synthesis, the Selection's own and those citing one of its
 * analyses (`records`, `materialRecords`), which a box leaves out. « Group
 * by » (a group of pressed buttons, kept for the tab in the store) lists
 * one row per identified material, or gathers them under each colour ×
 * material pair of the synthesis or each component they observe. A group
 * row carries its records' aggregate (best certainty, marked « best » over
 * several; the union of their colours, components, folios, elements by
 * level and evidence) and unfolds to its records, indented; records no
 * group holds follow the groups. Every name, colour, component, element
 * and analysis the linked selection holds is a toggle of its node with
 * the focus marks (`useLinkedMarks().focus`, `LinkedChip`); a row is tinted
 * by how its node stands to the focus and to the node previewed, and a
 * mouse resting on it previews that node. A record's name is its
 * materials, then its layers and document, its full name in the title.
 */
const props = defineProps<{
    records: readonly MaterialRecord[];
    pairs: readonly SynthesisPair[];
    canvases: readonly SynthesisCanvas[];
    /** The Selection's analyses, for the techniques of the evidence. */
    analyses: readonly AnalysisHit[];
}>();

const { $gettext, $ngettext, $pgettext, interpolate } = useGettext();
const store = useExplorerStore();
const marks = useLinkedMarks();

const includeCiting = ref(true);
const openGroups = ref<NodeId[]>([]);

const grouping = computed(() => store.materialsGrouping);
const counts = computed(() => materialCounts(props.records));
const shown = computed(() => shownRecords(props.records, includeCiting.value));
const slots = computed(() => selectionSlots(store.basket));
const canvasLabels = computed(
    () => new Map(props.canvases.map((entry) => [entry.canvas, entry.label])),
);
const techniques = computed(() => {
    const found = new Map<string, Technique>();
    for (const analysis of props.analyses) {
        if (analysis.technique) found.set(analysis.id, analysis.technique);
    }
    return found;
});
const options = computed<GroupingOption[]>(() => {
    const labels: Record<MaterialsGrouping, string> = {
        record: $pgettext("Group the identified materials by", "Record"),
        pair: $gettext("Colour × material"),
        component: $gettext("Component"),
    };
    return GROUPINGS.map((value) => ({ value, label: labels[value] }));
});
const nameHeading = computed(() => {
    switch (grouping.value) {
        case "pair":
            return $gettext("Colour × material");
        case "component":
            return $gettext("Component");
        default:
            return $gettext("Identified material");
    }
});
/** The heading of the fourth column: a component group lists its materials there. */
const componentHeading = computed(() =>
    grouping.value === "component"
        ? $gettext("Materials")
        : $gettext("Component"),
);
const citingLabel = computed(() =>
    interpolate(
        $gettext(
            "Also the materials citing an analysis of the Selection (%{n})",
        ),
        { n: counts.value.citing },
        true,
    ),
);
const rows = computed<Row[]>(() => {
    if (grouping.value === "record") {
        return shown.value.map((record) => recordRow(record, null));
    }
    const grouped: GroupedRecords =
        grouping.value === "pair"
            ? groupByPair(shown.value, props.pairs)
            : groupByComponent(shown.value);
    const result: Row[] = [];
    for (const group of grouped.groups) {
        const open = openGroups.value.includes(group.node);
        result.push(groupRow(group, open));
        if (open) {
            for (const record of group.records) {
                result.push(recordRow(record, group.node));
            }
        }
    }
    for (const record of grouped.rest) result.push(recordRow(record, null));
    return result;
});

function recordRow(record: MaterialRecord, parent: NodeId | null): Row {
    const summary = record.summary;
    const materials = summary.materials.map((entry) => entry.value);
    const documents = summary.objects
        .filter((object) => object.model !== "component")
        .map((object) => object.name.value);
    return {
        kind: "record",
        key: parent ? `${parent}/${record.id}` : record.id,
        node: materialNode(record.id),
        nested: parent !== null,
        open: false,
        name:
            materials.length > 0
                ? { value: joined(materials), lang: materials[0].label.lang }
                : summary.name,
        rest: [joined(summary.layers), documents.join(", ")]
            .filter((part) => part !== "")
            .join(" · "),
        title: summary.name.value,
        unpublished: summary.unpublished,
        certainty: bestConfidence([record]),
        best: false,
        colours: summary.colours,
        components: componentsOf(summary),
        materials: "",
        folios: foliosOf(record.canvases),
        levels: unionLevels([record]),
        evidence: summary.evidence,
        selection: recordSelection(record),
    };
}

function groupRow(group: MaterialGroup, open: boolean): Row {
    const records = group.records;
    const byPair = grouping.value === "pair";
    const selected = records.filter((record) => record.selected).length;
    return {
        kind: "group",
        key: group.node,
        node: group.node,
        nested: false,
        open,
        name: group.colour
            ? {
                  value: interpolate(
                      $gettext("%{colour} × %{material}"),
                      {
                          colour: group.colour.label.value,
                          material: group.name.value,
                      },
                      true,
                  ),
                  lang: group.name.lang,
              }
            : group.name,
        rest: interpolate(
            $ngettext(
                "%{n} identified material",
                "%{n} identified materials",
                records.length,
            ),
            { n: records.length },
            true,
        ),
        title: undefined,
        unpublished: false,
        certainty: bestConfidence(records),
        best: records.length > 1,
        colours: byPair
            ? group.colour
                ? [group.colour]
                : []
            : unionColours(records),
        components: byPair ? unionComponents(records) : [],
        materials: byPair ? "" : joined(unionMaterials(records)),
        folios: foliosOf(unionCanvases(records)),
        levels: unionLevels(records),
        evidence: unionEvidence(records),
        selection: {
            slots: [],
            cites: null,
            counts: { selected, citing: records.length - selected },
        },
    };
}

function recordSelection(record: MaterialRecord): SelectionCell {
    if (record.selected) {
        return {
            slots: (slots.value.get(record.id) ?? []).map(slotLabel),
            cites: null,
            counts: null,
        };
    }
    const cited = [
        ...new Set(record.cites.flatMap((id) => slots.value.get(id) ?? [])),
    ].sort((left, right) => left - right);
    return {
        slots: [],
        cites:
            cited.length === 0
                ? null
                : interpolate(
                      $gettext("cites %{slots}"),
                      { slots: cited.map(slotLabel).join(", ") },
                      true,
                  ),
        counts: null,
    };
}

function setGrouping(value: MaterialsGrouping): void {
    store.setMaterialsGrouping(value);
}

function toggleGroup(node: NodeId): void {
    openGroups.value = openGroups.value.includes(node)
        ? openGroups.value.filter((entry) => entry !== node)
        : [...openGroups.value, node];
}

/** Whether `node` can be pinned: always outside Compare, else when its graph holds it. */
function canToggle(node: NodeId): boolean {
    return !marks.linked || marks.linked.graph.value.nodes.has(node);
}

function joined(values: readonly ValueRef[]): string {
    return values.map((value) => value.label.value).join(", ");
}

/** The folios named by their label; those without one counted. */
function foliosOf(canvases: readonly string[]): string {
    const named = canvases.flatMap((canvas) => {
        const label = canvasLabels.value.get(canvas);
        return label ? [label] : [];
    });
    const others = canvases.length - named.length;
    if (others === 0) return named.join(", ");
    const counted = interpolate(
        named.length > 0
            ? $ngettext("%{n} other folio", "%{n} other folios", others)
            : $ngettext("%{n} folio", "%{n} folios", others),
        { n: others },
        true,
    );
    return [...named, counted].join(", ");
}

function citesTitle(cites: string): string {
    return interpolate(
        $gettext("Not in the Selection: %{cites}"),
        { cites },
        true,
    );
}

function countsText(counts: { selected: number; citing: number }): string {
    const own = interpolate(
        $gettext("%{n} of the Selection"),
        { n: counts.selected },
        true,
    );
    if (counts.citing === 0) return own;
    const citing = interpolate(
        $gettext("%{n} citing it"),
        { n: counts.citing },
        true,
    );
    return `${own} · ${citing}`;
}

function groupToggleLabel(row: Row): string {
    return interpolate(
        $gettext("Identified materials of %{name}"),
        { name: row.name.value },
        true,
    );
}
</script>

<template>
    <div class="materials-table">
        <div class="bar">
            <div class="grouping">
                <span>{{ $gettext("Group by") }}</span>
                <span
                    class="segmented"
                    role="group"
                    :aria-label="$gettext('Group the identified materials')"
                >
                    <button
                        v-for="option in options"
                        :key="option.value"
                        type="button"
                        :data-grouping="option.value"
                        :aria-pressed="
                            grouping === option.value ? 'true' : 'false'
                        "
                        @click="setGrouping(option.value)"
                    >
                        <span>{{ option.label }}</span>
                    </button>
                </span>
            </div>
            <label
                v-if="counts.citing > 0"
                class="citing"
            >
                <input
                    v-model="includeCiting"
                    type="checkbox"
                />
                <span>{{ citingLabel }}</span>
            </label>
        </div>
        <p
            v-if="shown.length === 0"
            class="empty"
        >
            <span>{{
                $gettext("No identified material of the Selection itself.")
            }}</span>
        </p>
        <div
            v-else
            class="scroll"
        >
            <table>
                <thead>
                    <tr>
                        <th scope="col">
                            <span>{{ nameHeading }}</span>
                        </th>
                        <th scope="col">
                            <span>{{ $gettext("Certainty") }}</span>
                        </th>
                        <th scope="col">
                            <span>{{ $gettext("Colour") }}</span>
                        </th>
                        <th scope="col">
                            <span>{{ componentHeading }}</span>
                        </th>
                        <th scope="col">
                            <span>{{ $gettext("Folio") }}</span>
                        </th>
                        <th scope="col">
                            <span>{{ $gettext("Elements") }}</span>
                        </th>
                        <th scope="col">
                            <span>{{ $gettext("Evidence") }}</span>
                        </th>
                        <th scope="col">
                            <span>{{ $gettext("Selection") }}</span>
                        </th>
                    </tr>
                </thead>
                <tbody>
                    <tr
                        v-for="row in rows"
                        :key="row.key"
                        :class="[row.kind, { nested: row.nested }]"
                        :data-key="row.key"
                        :data-rel="marks.rel(row.node)"
                        :data-preview="marks.previewRel(row.node)"
                        :style="marks.rowStyle(row.node)"
                        @pointerenter="marks.enter(row.node, $event)"
                        @pointerleave="marks.leave($event)"
                    >
                        <th
                            scope="row"
                            class="name"
                        >
                            <div class="lead">
                                <button
                                    v-if="row.kind === 'group'"
                                    type="button"
                                    class="caret"
                                    :aria-expanded="row.open ? 'true' : 'false'"
                                    :aria-label="groupToggleLabel(row)"
                                    @click="toggleGroup(row.node)"
                                >
                                    <span aria-hidden="true">▾</span>
                                </button>
                                <button
                                    v-if="canToggle(row.node)"
                                    type="button"
                                    class="toggle ms-focus"
                                    v-bind="marks.focus(row.node)"
                                    :title="row.title"
                                    :aria-pressed="marks.pressed(row.node)"
                                    @click="marks.toggle(row.node)"
                                >
                                    <FocusPip :node="row.node" />
                                    <span
                                        class="main"
                                        :lang="row.name.lang"
                                        >{{ row.name.value }}</span
                                    >
                                    <span
                                        v-if="row.rest"
                                        class="rest"
                                        >{{ row.rest }}</span
                                    >
                                </button>
                                <span
                                    v-else
                                    class="toggle plain-name"
                                    :title="row.title"
                                >
                                    <span
                                        class="main"
                                        :lang="row.name.lang"
                                        >{{ row.name.value }}</span
                                    >
                                    <span
                                        v-if="row.rest"
                                        class="rest"
                                        >{{ row.rest }}</span
                                    >
                                </span>
                                <span
                                    v-if="row.unpublished"
                                    class="badge"
                                >
                                    {{ $gettext("Draft") }}
                                </span>
                            </div>
                        </th>
                        <td>
                            <CertaintyScale
                                :confidence="row.certainty"
                                :best="row.best"
                            />
                        </td>
                        <td>
                            <ul
                                v-if="row.colours.length > 0"
                                class="chips"
                            >
                                <li
                                    v-for="colour in row.colours"
                                    :key="colour.id"
                                >
                                    <LinkedChip
                                        v-if="canToggle(colourNode(colour.id))"
                                        :node="colourNode(colour.id)"
                                        :text="colour.label.value"
                                        :lang="colour.label.lang"
                                    >
                                        <template #lead>
                                            <span
                                                class="swatch"
                                                aria-hidden="true"
                                            ></span>
                                        </template>
                                    </LinkedChip>
                                    <span
                                        v-else
                                        class="plain"
                                        :lang="colour.label.lang"
                                    >
                                        <span
                                            class="swatch"
                                            aria-hidden="true"
                                        ></span>
                                        <span>{{ colour.label.value }}</span>
                                    </span>
                                </li>
                            </ul>
                            <template v-else>
                                <span
                                    class="none"
                                    aria-hidden="true"
                                    >—</span
                                >
                                <span class="visually-hidden">{{
                                    $gettext("Not stated")
                                }}</span>
                            </template>
                        </td>
                        <td>
                            <span
                                v-if="row.materials"
                                class="materials"
                                >{{ row.materials }}</span
                            >
                            <ul
                                v-else-if="row.components.length > 0"
                                class="chips"
                            >
                                <li
                                    v-for="component in row.components"
                                    :key="component.id"
                                >
                                    <LinkedChip
                                        v-if="
                                            canToggle(
                                                componentNode(component.id),
                                            )
                                        "
                                        :node="componentNode(component.id)"
                                        :text="component.name.value"
                                        :lang="component.name.lang"
                                    >
                                        <template #lead>
                                            <span
                                                class="glyph"
                                                aria-hidden="true"
                                            ></span>
                                        </template>
                                    </LinkedChip>
                                    <span
                                        v-else
                                        class="plain"
                                        :lang="component.name.lang"
                                    >
                                        <span
                                            class="glyph"
                                            aria-hidden="true"
                                        ></span>
                                        <span>{{ component.name.value }}</span>
                                    </span>
                                </li>
                            </ul>
                            <template v-else>
                                <span
                                    class="none"
                                    aria-hidden="true"
                                    >—</span
                                >
                                <span class="visually-hidden">{{
                                    $gettext("Not stated")
                                }}</span>
                            </template>
                        </td>
                        <td class="folios">
                            <span>{{ row.folios }}</span>
                        </td>
                        <td>
                            <ElementLevels :levels="row.levels" />
                        </td>
                        <td>
                            <MaterialEvidence
                                :evidence="row.evidence"
                                :techniques="techniques"
                            />
                        </td>
                        <td>
                            <div class="selection">
                                <template v-if="row.selection.counts">
                                    <span
                                        class="count"
                                        aria-hidden="true"
                                        >{{
                                            row.selection.counts.selected
                                        }}</span
                                    >
                                    <span
                                        v-if="row.selection.counts.citing > 0"
                                        class="tag"
                                        aria-hidden="true"
                                        >+{{
                                            row.selection.counts.citing
                                        }}</span
                                    >
                                    <span class="visually-hidden">{{
                                        countsText(row.selection.counts)
                                    }}</span>
                                </template>
                                <span
                                    v-else-if="row.selection.cites"
                                    class="tag"
                                    :title="citesTitle(row.selection.cites)"
                                    >{{ row.selection.cites }}</span
                                >
                                <template v-else>
                                    <span
                                        v-for="tag in row.selection.slots"
                                        :key="tag"
                                        class="tag sel"
                                        >{{ tag }}</span
                                    >
                                </template>
                            </div>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
</template>

<style scoped>
.materials-table {
    display: grid;
    gap: 0.625rem;
    font-size: 0.8125rem;
}

.materials-table .bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem 1rem;
    color: var(--ink-muted);
}

.materials-table .grouping,
.materials-table .citing {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
}

.materials-table .segmented {
    display: inline-flex;
    padding: 0.125rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
}

.materials-table .segmented button {
    min-block-size: 1.75rem;
    padding-inline: 0.75rem;
    border: none;
    border-radius: 999rem;
    background: none;
    color: var(--ink-muted);
    font: inherit;
    white-space: nowrap;
    cursor: pointer;
}

.materials-table .segmented button[aria-pressed="true"] {
    background: var(--ink);
    color: var(--surface);
    font-weight: 600;
}

.materials-table .citing input {
    inline-size: 1rem;
    block-size: 1rem;
    accent-color: var(--ink);
}

.materials-table button:focus-visible,
.materials-table .citing input:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.1875rem;
}

.materials-table .empty {
    color: var(--ink-muted);
}

.materials-table .scroll {
    overflow-x: auto;
}

.materials-table table {
    inline-size: 100%;
    border-collapse: collapse;
}

.materials-table th,
.materials-table td {
    padding: 0.5rem;
    border-block-end: 0.0625rem solid var(--border);
    text-align: start;
    vertical-align: top;
}

.materials-table thead th {
    padding-block: 0.375rem;
    border-block-end-color: var(--border-hover);
    color: var(--ink-muted);
    font-weight: 600;
    white-space: nowrap;
}

.materials-table tbody th {
    font-weight: 400;
}

.materials-table tbody tr {
    transition:
        background-color var(--dur-med, 260ms),
        color var(--dur-med, 260ms);
}

.materials-table tbody tr > :first-child {
    position: relative;
}

.materials-table tbody tr > :first-child::before {
    position: absolute;
    inset-block: 0;
    inset-inline-start: 0;
    inline-size: 0;
    background: var(--bar, var(--focus-1));
    content: "";
    transition: inline-size var(--dur-med, 260ms) var(--ease-out-expo);
}

.materials-table
    tbody
    tr:is([data-rel="self"], [data-rel="direct"], [data-rel="evidence"]) {
    background: color-mix(
        in srgb,
        var(--h1, var(--focus-1)) 6%,
        var(--surface)
    );
}

.materials-table tbody tr[data-rel="self"] > :first-child::before {
    inline-size: 0.25rem;
}

.materials-table tbody tr[data-rel="direct"] > :first-child::before {
    inline-size: 0.1875rem;
}

.materials-table tbody tr[data-rel="evidence"] > :first-child::before {
    inline-size: 0.0625rem;
}

.materials-table tbody tr[data-rel="none"] {
    color: var(--ink-muted);
}

.materials-table tbody tr[data-preview] {
    background: color-mix(
        in srgb,
        var(--hp, var(--focus-1)) 5%,
        var(--surface)
    );
}

.materials-table tbody tr[data-preview="evidence"] {
    background: color-mix(
        in srgb,
        var(--hp, var(--focus-1)) 3%,
        var(--surface)
    );
}

.materials-table tbody tr.group > * {
    padding-block: 0.4375rem;
    border-block-end-color: var(--border-hover);
    background: var(--bg-warm);
}

.materials-table
    tbody
    tr.group:is([data-rel="self"], [data-rel="direct"], [data-rel="evidence"])
    > * {
    background: color-mix(
        in srgb,
        var(--h1, var(--focus-1)) 9%,
        var(--bg-warm)
    );
}

.materials-table tbody tr.nested > :first-child {
    padding-inline-start: 2.25rem;
}

.materials-table tbody tr.nested > :first-child::before {
    inset-inline-start: 1.375rem;
}

.materials-table .lead {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    gap: var(--focus-room) 0.375rem;
}

.materials-table .caret {
    inline-size: 1.5rem;
    block-size: 1.5rem;
    border: none;
    border-radius: 0.25rem;
    background: transparent;
    color: var(--ink-muted);
    font: inherit;
    cursor: pointer;
    transition: transform var(--dur-fast, 160ms);
}

.materials-table .caret[aria-expanded="false"] {
    transform: rotate(-90deg);
}

.materials-table .toggle {
    --r: 0.375rem;
    --link-pip: 0.8125rem;
    display: inline-grid;
    max-inline-size: 100%;
    padding-block: 0.25rem;
    padding-inline: 0.5rem;
    border: none;
    border-radius: 0.375rem;
    background: var(--surface);
    box-shadow: inset 0 0 0 0.0625rem var(--border-hover);
    color: var(--ink);
    font: inherit;
    line-height: 1.3;
    text-align: start;
}

.materials-table button.toggle {
    min-block-size: var(--explorer-target, 2.75rem);
    cursor: pointer;
}

.materials-table .plain-name {
    box-shadow: none;
    background: transparent;
}

.materials-table .toggle .main {
    font-weight: 600;
}

.materials-table .toggle[aria-pressed="true"] .main {
    font-weight: 700;
}

.materials-table .toggle .rest {
    color: var(--ink-muted);
    font-size: 0.6875rem;
}

.materials-table .badge,
.materials-table .tag {
    display: inline-block;
    padding-inline: 0.375rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    color: var(--ink-muted);
    font-size: 0.6875rem;
    white-space: nowrap;
}

.materials-table .tag.sel {
    border-color: transparent;
    background: var(--ink);
    color: var(--surface);
}

.materials-table .selection {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    align-items: baseline;
}

.materials-table .count {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
}

.materials-table .chips {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--focus-room) 0.25rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.materials-table .plain {
    display: inline-flex;
    align-items: center;
    gap: 0.3125rem;
    font-size: 0.75rem;
}

.materials-table .swatch {
    flex: none;
    inline-size: 0.75rem;
    block-size: 0.75rem;
    border-radius: 0.1875rem;
    box-shadow: inset 0 0 0 0.0625rem var(--ink-dim);
}

.materials-table .glyph {
    flex: none;
    inline-size: 0.6875rem;
    block-size: 0.6875rem;
    border: 0.09375rem dashed var(--ink-dim);
    border-radius: 0.125rem;
}

.materials-table .folios {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    white-space: nowrap;
}

.materials-table .none {
    color: var(--ink-muted);
}

.materials-table .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

@media (prefers-reduced-motion: reduce) {
    .materials-table tbody tr,
    .materials-table tbody tr > :first-child::before,
    .materials-table .caret {
        transition: none;
    }
}
</style>
