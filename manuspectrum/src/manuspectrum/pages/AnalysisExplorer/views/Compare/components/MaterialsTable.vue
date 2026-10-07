<script setup lang="ts">
import { computed, ref } from "vue";
import { useGettext } from "vue3-gettext";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
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
    ColourRef,
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
    /** Slot tags (A1…) of a record of the Selection, each with its title. */
    slots: { tag: string; title: string }[];
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
    /** Every other record of the record grouping. */
    zebra: boolean;
    open: boolean;
    name: Label;
    /** A pair group's colour and material, drawn apart in its name. */
    pair: { colour: ColourRef; material: Label } | null;
    rest: string;
    /** A record's full name. */
    title: string | undefined;
    unpublished: boolean;
    certainty: RankedValue | null;
    colours: ColourRef[];
    components: Ref[];
    /** A component group's materials, in its Component column. */
    materials: string;
    /** Folio labels as stored, then the count of those without one. */
    folios: string[];
    levels: ElementLevel[];
    evidence: NamedRef[];
    selection: SelectionCell;
}

const GROUPINGS: readonly MaterialsGrouping[] = ["record", "pair", "component"];
/** The folios a cell lists before its « more » button. */
const FOLIOS_SHOWN = 3;

/**
 * The Materials window of Compare: one table of every identified material
 * of the synthesis, the Selection's own and those citing one of its
 * analyses (`records`, `materialRecords`), which a box leaves out. « Group
 * by » (a group of pressed buttons, kept for the tab in the store) lists
 * one row per identified material, or gathers them under each colour ×
 * material pair of the synthesis or each component they observe. A group
 * row carries its records' aggregate (the highest certainty; the union of
 * their colours, components, folios, elements by level and evidence) and
 * unfolds to its records, indented; records no group holds follow the
 * groups. Every name, colour, component, element and analysis the linked
 * selection holds is a toggle of its node with the focus marks
 * (`useLinkedMarks().focus`, `LinkedChip`); a row is tinted by how its
 * node stands to the focus and to the node previewed, and a mouse resting
 * on it previews that node. A record's name is its materials, its layers
 * and document under it, its full name in the title. A colour shows the
 * swatch the server serves (`colour.swatch`), hatched when the list has none. A
 * cell lists `FOLIOS_SHOWN` folios, a button unfolds the others.
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
const openFolios = ref<string[]>([]);

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
const rows = computed<Row[]>(() => {
    if (grouping.value === "record") {
        return shown.value.map((record, index) =>
            recordRow(record, null, index % 2 === 1),
        );
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
                result.push(recordRow(record, group.node, false));
            }
        }
    }
    for (const record of grouped.rest) {
        result.push(recordRow(record, null, false));
    }
    return result;
});

function recordRow(
    record: MaterialRecord,
    parent: NodeId | null,
    zebra: boolean,
): Row {
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
        zebra,
        open: false,
        name:
            materials.length > 0
                ? { value: joined(materials), lang: materials[0].label.lang }
                : summary.name,
        pair: null,
        rest: [joined(summary.layers), documents.join(", ")]
            .filter((part) => part !== "")
            .join(" · "),
        title: summary.name.value,
        unpublished: summary.unpublished,
        certainty: bestConfidence([record]),
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
        zebra: false,
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
        pair: group.colour
            ? { colour: group.colour, material: group.name }
            : null,
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
            slots: (slots.value.get(record.id) ?? []).map((slot) => ({
                tag: slotLabel(slot),
                title: interpolate(
                    $gettext("In the Selection (%{slot})"),
                    { slot: slotLabel(slot) },
                    true,
                ),
            })),
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

/** A row name's attributes: a toggle of its node when it can be pinned, plain text otherwise. */
function nameBinding(row: Row): Record<string, unknown> {
    if (!canToggle(row.node)) return { class: "toggle plain-name" };
    return {
        ...marks.focus(row.node),
        class: "toggle ms-focus",
        type: "button",
        "aria-pressed": marks.pressed(row.node),
    };
}

function toggleName(row: Row): void {
    if (canToggle(row.node)) marks.toggle(row.node);
}

/** Whether `node` can be pinned: always outside Compare, else when its graph holds it. */
function canToggle(node: NodeId): boolean {
    return !marks.linked || marks.linked.graph.value.nodes.has(node);
}

function joined(values: readonly ValueRef[]): string {
    return values.map((value) => value.label.value).join(", ");
}

/** The folios named by their label as stored; those without one counted in a last entry. */
function foliosOf(canvases: readonly string[]): string[] {
    const named = canvases.flatMap((canvas) => {
        const label = canvasLabels.value.get(canvas);
        return label ? [label] : [];
    });
    const others = canvases.length - named.length;
    if (others === 0) return named;
    const counted = interpolate(
        named.length > 0
            ? $ngettext("%{n} other folio", "%{n} other folios", others)
            : $ngettext("%{n} folio", "%{n} folios", others),
        { n: others },
        true,
    );
    return [...named, counted];
}

/** The folios a row shows: the first `FOLIOS_SHOWN`, all once unfolded. */
function shownFolios(row: Row): string[] {
    return openFolios.value.includes(row.key)
        ? row.folios
        : row.folios.slice(0, FOLIOS_SHOWN);
}

function toggleFolios(key: string): void {
    openFolios.value = openFolios.value.includes(key)
        ? openFolios.value.filter((entry) => entry !== key)
        : [...openFolios.value, key];
}

function moreFoliosText(row: Row): string {
    const hidden = row.folios.length - FOLIOS_SHOWN;
    return interpolate(
        $ngettext("%{n} more folio", "%{n} more folios", hidden),
        { n: hidden },
        true,
    );
}

function citesTitle(cites: string): string {
    return interpolate(
        $gettext("Not in the Selection: %{cites}"),
        { cites },
        true,
    );
}

function selectedText(n: number): string {
    return interpolate($gettext("%{n} of the Selection"), { n }, true);
}

function citingText(n: number): string {
    return interpolate($gettext("%{n} citing it"), { n }, true);
}

/** The swatch style of a colour; none for a colour without one (hatched). */
function swatchStyle(colour: ColourRef): Record<string, string> | undefined {
    return colour.swatch ? { "--swatch": colour.swatch } : undefined;
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
            <div
                v-if="counts.citing > 0"
                class="citing"
            >
                <label>
                    <input
                        v-model="includeCiting"
                        type="checkbox"
                    />
                    <span>{{
                        $gettext("Materials citing the Selection")
                    }}</span>
                    <span class="count">{{ counts.citing }}</span>
                </label>
                <span class="help">
                    <IconButton
                        icon="info-circle"
                        :label="
                            $gettext('About the materials citing the Selection')
                        "
                        :description="
                            $gettext(
                                'Adds the identified materials that are not in your Selection but cite one of its analyses as evidence. The Selection column then reads “cites A3”.',
                            )
                        "
                    />
                </span>
            </div>
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
                <colgroup>
                    <col class="name" />
                    <col class="certainty" />
                    <col class="colour" />
                    <col class="component" />
                    <col class="folio" />
                    <col class="elements" />
                    <col class="evidence" />
                    <col class="selection" />
                </colgroup>
                <thead>
                    <tr>
                        <th scope="col">
                            <span>{{ nameHeading }}</span>
                        </th>
                        <th scope="col">
                            <span class="heading">
                                <span>{{ $gettext("Certainty") }}</span>
                                <span class="help">
                                    <IconButton
                                        icon="info-circle"
                                        tip-align="start"
                                        :label="$gettext('About the certainty')"
                                        :description="
                                            $gettext(
                                                'How reliable the identification is. A group row shows the highest certainty among its materials.',
                                            )
                                        "
                                    />
                                </span>
                            </span>
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
                        :class="[
                            row.kind,
                            { nested: row.nested, zebra: row.zebra },
                        ]"
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
                                    <svg
                                        viewBox="0 0 10 10"
                                        aria-hidden="true"
                                        focusable="false"
                                    >
                                        <path d="M1.5 3.2 5 6.8l3.5-3.6" />
                                    </svg>
                                </button>
                                <div class="who">
                                    <component
                                        :is="
                                            canToggle(row.node)
                                                ? 'button'
                                                : 'span'
                                        "
                                        v-bind="nameBinding(row)"
                                        :title="row.title"
                                        @click="toggleName(row)"
                                    >
                                        <FocusPip
                                            v-if="canToggle(row.node)"
                                            :node="row.node"
                                        />
                                        <span
                                            v-if="row.pair"
                                            class="swatch large"
                                            :class="{
                                                unknown: !swatchStyle(
                                                    row.pair.colour,
                                                ),
                                            }"
                                            :style="
                                                swatchStyle(row.pair.colour)
                                            "
                                            aria-hidden="true"
                                        ></span>
                                        <span
                                            v-else-if="
                                                row.kind === 'group' &&
                                                grouping === 'component'
                                            "
                                            class="glyph large"
                                            aria-hidden="true"
                                        ></span>
                                        <span
                                            v-if="row.pair"
                                            class="main"
                                            ><span
                                                :lang="
                                                    row.pair.colour.label.lang
                                                "
                                                >{{
                                                    row.pair.colour.label.value
                                                }}</span
                                            ><span class="times"> × </span
                                            ><span
                                                :lang="row.pair.material.lang"
                                                >{{
                                                    row.pair.material.value
                                                }}</span
                                            ></span
                                        >
                                        <span
                                            v-else
                                            class="main"
                                            :lang="row.name.lang"
                                            >{{ row.name.value }}</span
                                        >
                                    </component>
                                    <span
                                        v-if="row.rest || row.unpublished"
                                        class="rest"
                                    >
                                        <span v-if="row.rest">{{
                                            row.rest
                                        }}</span>
                                        <span
                                            v-if="row.unpublished"
                                            class="draft"
                                            >{{ $gettext("Draft") }}</span
                                        >
                                    </span>
                                </div>
                            </div>
                        </th>
                        <td>
                            <CertaintyScale :confidence="row.certainty" />
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
                                        class="colour"
                                        :node="colourNode(colour.id)"
                                        :text="colour.label.value"
                                        :lang="colour.label.lang"
                                    >
                                        <template #lead>
                                            <span
                                                class="swatch"
                                                :class="{
                                                    unknown:
                                                        !swatchStyle(colour),
                                                }"
                                                :style="swatchStyle(colour)"
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
                                            :class="{
                                                unknown: !swatchStyle(colour),
                                            }"
                                            :style="swatchStyle(colour)"
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
                                        class="component"
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
                        <td>
                            <ul
                                v-if="row.folios.length > 0"
                                class="folios"
                            >
                                <li
                                    v-for="folio in shownFolios(row)"
                                    :key="folio"
                                >
                                    {{ folio }}
                                </li>
                                <li v-if="row.folios.length > FOLIOS_SHOWN">
                                    <button
                                        type="button"
                                        class="more"
                                        :aria-expanded="
                                            openFolios.includes(row.key)
                                                ? 'true'
                                                : 'false'
                                        "
                                        @click="toggleFolios(row.key)"
                                    >
                                        {{
                                            openFolios.includes(row.key)
                                                ? $gettext("Fewer folios")
                                                : moreFoliosText(row)
                                        }}
                                    </button>
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
                                        v-if="row.selection.counts.selected > 0"
                                        class="tally own"
                                        >{{
                                            selectedText(
                                                row.selection.counts.selected,
                                            )
                                        }}</span
                                    >
                                    <span
                                        v-if="row.selection.counts.citing > 0"
                                        class="tally cite"
                                        >{{
                                            citingText(
                                                row.selection.counts.citing,
                                            )
                                        }}</span
                                    >
                                </template>
                                <span
                                    v-else-if="row.selection.cites"
                                    class="badge cite"
                                    :title="citesTitle(row.selection.cites)"
                                    >{{ row.selection.cites }}</span
                                >
                                <template v-else>
                                    <span
                                        v-for="slot in row.selection.slots"
                                        :key="slot.tag"
                                        class="badge own"
                                        :title="slot.title"
                                    >
                                        <svg
                                            viewBox="0 0 9 11"
                                            aria-hidden="true"
                                            focusable="false"
                                        >
                                            <path d="M0 0h9v11L4.5 8 0 11z" />
                                        </svg>
                                        <span>{{ slot.tag }}</span>
                                    </span>
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
    grid-template-rows: auto minmax(0, 1fr);
    gap: 0.5rem;
    block-size: 100%;
    font-size: 0.8125rem;
}

.materials-table .bar {
    position: relative;
    z-index: 6;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem 1.25rem;
    color: var(--ink-muted);
}

.materials-table .grouping,
.materials-table .citing,
.materials-table .citing label {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
}

.materials-table .grouping {
    font-size: 0.75rem;
}

.materials-table .citing {
    gap: 0.125rem;
}

.materials-table .segmented {
    display: inline-flex;
    padding: 0.1875rem;
    border-radius: 999rem;
    background: var(--bg-alt);
    box-shadow: inset 0 0 0 0.0625rem var(--border);
}

.materials-table .segmented button {
    min-block-size: 1.75rem;
    padding-inline: 0.75rem;
    border: none;
    border-radius: 999rem;
    background: none;
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.78125rem;
    white-space: nowrap;
    cursor: pointer;
    transition:
        background-color var(--dur-fast, 160ms),
        color var(--dur-fast, 160ms);
}

.materials-table .segmented button:hover {
    color: var(--ink);
}

.materials-table .segmented button[aria-pressed="true"] {
    background: var(--surface);
    box-shadow:
        0 0.0625rem 0.125rem rgb(26 26 46 / 0.08),
        inset 0 0 0 0.0625rem var(--seg-on-rule);
    color: var(--seg-on-ink);
    font-weight: 600;
}

.materials-table .citing label {
    min-block-size: 1.75rem;
    color: var(--ink);
    font-size: 0.78125rem;
    cursor: pointer;
}

.materials-table .citing input {
    inline-size: 1rem;
    block-size: 1rem;
    margin: 0;
    accent-color: var(--accent-text);
}

.materials-table .citing .count {
    padding-inline: 0.3125rem;
    border: 0.0625rem dashed var(--sel-cite-rule);
    border-radius: 0.25rem;
    color: var(--sel-cite-ink);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
}

.materials-table .help {
    display: inline-flex;
}

.materials-table .help :deep(.icon-button-control) {
    min-inline-size: 1.5rem;
    min-block-size: 1.5rem;
    color: var(--accent-text);
}

.materials-table .help :deep(.icon) {
    inline-size: 1rem;
    block-size: 1rem;
}

.materials-table .help :deep(.bubble) {
    max-inline-size: min(20rem, 80vw);
    color: var(--surface);
    font-size: 0.75rem;
    font-weight: 400;
    letter-spacing: normal;
    text-transform: none;
    white-space: normal;
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
    min-block-size: 0;
    overflow: auto;
    padding-block-start: var(--focus-room);
}

.materials-table table {
    inline-size: 100%;
    min-inline-size: 64rem;
    border-collapse: separate;
    border-spacing: 0;
}

.materials-table col.name {
    inline-size: 17rem;
}

.materials-table col.certainty {
    inline-size: 9.5rem;
}

.materials-table col.colour {
    inline-size: 7.5rem;
}

.materials-table col.component {
    inline-size: 12rem;
}

.materials-table col.folio {
    inline-size: 6.75rem;
}

.materials-table col.elements {
    inline-size: 13rem;
}

.materials-table col.evidence {
    inline-size: 11rem;
}

.materials-table col.selection {
    inline-size: 8.5rem;
}

.materials-table th,
.materials-table td {
    padding-block: 0.4375rem;
    padding-inline: 0.5rem;
    border-block-end: 0.0625rem solid rgb(26 26 46 / 0.045);
    text-align: start;
    vertical-align: top;
}

.materials-table thead th {
    position: sticky;
    z-index: 5;
    inset-block-start: calc(-1 * var(--focus-room));
    padding-block: 0.375rem 0.4375rem;
    border-block-end-color: var(--mt-rule);
    background: var(--surface);
    color: var(--ink-muted);
    font-size: 0.6875rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    line-height: 1.2;
    text-transform: uppercase;
    white-space: nowrap;
}

.materials-table thead .heading {
    display: inline-flex;
    align-items: center;
    gap: 0.125rem;
    margin-block: -0.25rem;
}

.materials-table tbody th {
    font-weight: 400;
}

.materials-table tbody tr {
    transition:
        background-color var(--dur-med, 260ms),
        color var(--dur-med, 260ms);
}

.materials-table tbody tr.zebra {
    background: var(--mt-zebra);
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

.materials-table tbody tr[data-rel="none"] .certainty-scale {
    opacity: 0.6;
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
    padding-block: 0.5rem;
    border-block-start: 0.0625rem solid var(--mt-rule);
    border-block-end: 0;
    background: var(--mt-band);
}

.materials-table tbody tr.group:first-child > * {
    border-block-start: 0;
}

.materials-table
    tbody
    tr.group:is([data-rel="self"], [data-rel="direct"], [data-rel="evidence"])
    > * {
    background: color-mix(
        in srgb,
        var(--h1, var(--focus-1)) 8%,
        var(--mt-band)
    );
}

.materials-table tbody tr.group[data-preview] > * {
    background: color-mix(
        in srgb,
        var(--hp, var(--focus-1)) 6%,
        var(--mt-band)
    );
}

.materials-table tbody tr.nested > :first-child {
    padding-inline-start: 2.125rem;
}

.materials-table tbody tr.nested > :first-child::before {
    inset-inline-start: 1rem;
}

.materials-table tbody tr.nested > :first-child::after {
    position: absolute;
    inset-block: 0;
    inset-inline-start: 1.0625rem;
    inline-size: 0.0625rem;
    background: var(--mt-rule);
    content: "";
}

.materials-table .lead {
    display: flex;
    align-items: flex-start;
    gap: 0.25rem;
    min-inline-size: 0;
}

.materials-table .caret {
    display: inline-grid;
    flex: none;
    place-items: center;
    inline-size: 1.5rem;
    block-size: 1.5rem;
    margin-block-start: 0.25rem;
    padding: 0;
    border: none;
    border-radius: 0.3125rem;
    background: transparent;
    color: var(--accent-text);
    cursor: pointer;
    transition:
        transform var(--dur-fast, 160ms),
        background-color var(--dur-fast, 160ms);
}

.materials-table .caret:hover {
    background: rgb(160 125 28 / 0.1);
}

.materials-table .caret svg {
    inline-size: 0.625rem;
    block-size: 0.625rem;
    fill: none;
    stroke: currentColor;
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-width: 1.6;
}

.materials-table .caret[aria-expanded="false"] {
    transform: rotate(-90deg);
}

.materials-table .who {
    display: grid;
    gap: 0.0625rem;
    min-inline-size: 0;
}

.materials-table .toggle {
    --r: 0.375rem;
    --link-pip: 0.8125rem;
    display: inline-flex;
    align-items: center;
    justify-self: start;
    gap: 0.4375rem;
    max-inline-size: 100%;
    min-block-size: var(--explorer-target, 2rem);
    padding-block: 0.1875rem;
    padding-inline: 0.375rem;
    border: none;
    border-radius: 0.375rem;
    background: transparent;
    color: var(--ink);
    font: inherit;
    font-weight: 600;
    line-height: 1.25;
    text-align: start;
}

.materials-table button.toggle {
    cursor: pointer;
}

.materials-table button.toggle:hover {
    background: rgb(26 26 46 / 0.04);
}

/* A name stays text-like when unlinked: the fade of `.ms-focus` is for boxed toggles. */
.materials-table .toggle.ms-focus[data-rel="none"] {
    background: transparent !important;
}

.materials-table .toggle .main {
    min-inline-size: 0;
    overflow-wrap: anywhere;
}

.materials-table .toggle[aria-pressed="true"],
.materials-table .group .toggle[data-rel="self"] {
    font-weight: 700;
}

.materials-table .group .toggle {
    font-family: var(--font-display);
    font-size: 1.0625rem;
    letter-spacing: 0.005em;
    line-height: 1.15;
}

.materials-table .group .toggle .times {
    color: var(--ink-dim);
    font-family: var(--font-body);
    font-size: 0.75rem;
}

.materials-table .rest {
    padding-inline-start: 0.375rem;
    color: var(--ink-muted);
    font-size: 0.6875rem;
}

.materials-table .group .rest {
    font-size: 0.71875rem;
    font-variant-numeric: tabular-nums;
}

.materials-table .draft {
    display: inline-block;
    margin-inline-start: 0.375rem;
    padding-inline: 0.3125rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    font-size: 0.625rem;
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

.materials-table .linked-chip.colour {
    padding-inline-start: 0.25rem;
}

.materials-table .linked-chip.component {
    --chip-max: 11rem;
}

.materials-table .plain {
    display: inline-flex;
    align-items: center;
    gap: 0.3125rem;
    font-size: 0.75rem;
}

.materials-table .swatch {
    flex: none;
    inline-size: 0.875rem;
    block-size: 0.875rem;
    border-radius: 0.25rem;
    background: var(--swatch);
    box-shadow:
        inset 0 0 0 0.0625rem rgb(26 26 46 / 0.18),
        inset 0 0.0625rem 0 rgb(255 255 255 / 0.25);
}

.materials-table .swatch.unknown {
    background: repeating-linear-gradient(
        135deg,
        transparent 0 0.125rem,
        rgb(26 26 46 / 0.22) 0.125rem 0.1875rem
    );
}

.materials-table .swatch.large {
    inline-size: 1rem;
    block-size: 1rem;
}

.materials-table .glyph {
    flex: none;
    inline-size: 0.625rem;
    block-size: 0.625rem;
    border: 0.09375rem dashed var(--ink-dim);
    border-radius: 0.125rem;
}

.materials-table .glyph.large {
    inline-size: 0.75rem;
    block-size: 0.75rem;
}

.materials-table .materials {
    font-size: 0.78125rem;
    line-height: 1.35;
}

.materials-table .folios {
    margin: 0;
    padding: 0;
    color: var(--ink);
    font-family: var(--font-mono);
    font-size: 0.75rem;
    line-height: 1.5;
    list-style: none;
}

.materials-table .folios li {
    white-space: nowrap;
}

.materials-table .folios .more {
    padding: 0;
    border: none;
    background: none;
    color: var(--accent-text);
    font-family: var(--font-body);
    font-size: 0.6875rem;
    font-weight: 600;
    text-decoration: underline dotted;
    text-underline-offset: 0.1875rem;
    cursor: pointer;
}

.materials-table .selection {
    display: grid;
    justify-items: start;
    gap: 0.25rem;
    font-size: 0.71875rem;
}

.materials-table .badge {
    display: inline-flex;
    align-items: center;
    gap: 0.3125rem;
    min-block-size: 1.375rem;
    padding-inline: 0.4375rem;
    border-radius: 0.3125rem;
    font-weight: 600;
    white-space: nowrap;
}

.materials-table .badge.own {
    background: var(--sel-own-bg);
    box-shadow: inset 0 0 0 0.0625rem var(--sel-own-rule);
    color: var(--sel-own-ink);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
}

.materials-table .badge.own svg {
    inline-size: 0.5625rem;
    block-size: 0.6875rem;
    fill: currentColor;
}

.materials-table .badge.cite {
    border: 0.0625rem dashed var(--sel-cite-rule);
    color: var(--sel-cite-ink);
    font-weight: 500;
}

.materials-table .tally {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    color: var(--ink-muted);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}

.materials-table .tally::before {
    flex: none;
    inline-size: 0.625rem;
    block-size: 0.625rem;
    border-radius: 0.1875rem;
    content: "";
}

.materials-table .tally.own::before {
    background: var(--sel-own-bg);
    box-shadow: inset 0 0 0 0.0625rem var(--sel-own-rule);
}

.materials-table .tally.cite::before {
    border: 0.0625rem dashed var(--sel-cite-rule);
}

.materials-table .none {
    color: var(--ink-dim);
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
    .materials-table .caret,
    .materials-table .segmented button {
        transition: none;
    }
}

@media (forced-colors: active) {
    .materials-table .swatch {
        forced-color-adjust: none;
    }

    .materials-table .segmented button[aria-pressed="true"] {
        outline: 0.125rem solid Highlight;
    }
}
</style>
