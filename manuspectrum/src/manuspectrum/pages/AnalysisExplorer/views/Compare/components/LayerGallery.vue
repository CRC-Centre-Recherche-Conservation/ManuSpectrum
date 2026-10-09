<script setup lang="ts">
import { computed, nextTick, ref, useId, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import HelpTip from "@/manuspectrum/pages/AnalysisExplorer/components/HelpTip.vue";
import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";
import LayerThumb from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LayerThumb.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import { nextId } from "@/manuspectrum/pages/AnalysisExplorer/folio/roving.ts";
import { foldText } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import { shortAnalysisName } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/analysis-short-name.ts";
import { tagText } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tag-text.ts";
import {
    compareFamilies,
    layerTag,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";
import {
    CAPTURE_PREFIX,
    captureThumbnail,
    PANES_SHOWN,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import {
    analysisNode,
    elementNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { focusHue } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import { atomicNumber } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/periodic.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LayerTag } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";
import type {
    Captures,
    TableGrouping,
    TableState,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

const PANE_LETTERS = ["A", "B", "C", "D"] as const;
const GROUP_PLACE_MAX = 4;
const ROVING_KEYS = new Set([
    "ArrowLeft",
    "ArrowRight",
    "ArrowUp",
    "ArrowDown",
    "Home",
    "End",
]);

interface Entry {
    layer: FileLayer;
    line: MapLine;
    tag: LayerTag;
    text: string;
    nodes: ReturnType<typeof elementNode>[];
    /** The analysis whose folio capture this entry is, null for a manifest layer. */
    capture: string | null;
}

interface Group {
    id: string;
    title: string;
    fullTitle: string | null;
    node: ReturnType<typeof analysisNode> | null;
    meta: string;
    note: string | null;
    entries: Entry[];
    compare: boolean;
}

/**
 * Every imaging canvas of the Selection, whatever its manifest, as small
 * images grouped by analysis or, once layers carry a declared tag, by
 * element or band (the families shared across analyses first, the content
 * alone after, then « Unclassified »). Without any tag the grouping is
 * forced to Analysis and its segment disabled: nothing else is drawn. A
 * click lays a canvas in the target pane (`place`), or adds it to or takes it
 * out of the stack (`toggle-stack`); a drag carries its id; a group lays its
 * first layers (`place-group`) or, for a family shared by analyses, compares
 * them (`compare`). The thumbnails are one tab stop. The panes marked on a
 * thumbnail and offered as targets are those the layout shows (A for one pane,
 * A and B for the curtain and two panes, A to D for four); a layer in the
 * stack is marked only in the Stack layout. The state of the other panes is
 * kept, not drawn. A folio capture of a selected analysis comes last in its
 * group (under « Unclassified » when grouped by tag), marked « this browser »
 * and deletable (`delete-capture`).
 */
const props = defineProps<{
    maps: readonly MapLine[];
    state: TableState;
    captures?: Captures;
}>();
const emit = defineEmits<{
    place: [canvas: string];
    "toggle-stack": [canvas: string];
    "set-target": [pane: number];
    "group-change": [grouping: TableGrouping];
    "place-group": [canvases: string[]];
    compare: [canvases: string[]];
    "delete-capture": [analysisId: string];
}>();

const { $gettext, $ngettext, interpolate } = useGettext();
const marks = useLinkedMarks();
const root = useTemplateRef<HTMLElement>("root");

const filtersId = useId();
const filtersOpen = ref(false);
const query = ref("");
const only = ref<string | null>(null);
const roving = ref<string | null>(null);

const entries = computed<Entry[]>(() => {
    const sorted = [...props.maps].sort((a, b) => a.slot - b.slot);
    const last = new Map(sorted.map((line) => [line.analysis.id, line]));
    return sorted.flatMap((line) => {
        const own = line.file.layers.map((layer): Entry => {
            const tag = layerTag(layer);
            return {
                layer,
                line,
                tag,
                text: tag ? tagText(tag.parts, { $gettext, interpolate }) : "",
                nodes: layer.elements.flatMap((item) =>
                    item.symbol ? [elementNode(item.symbol)] : [],
                ),
                capture: null,
            };
        });
        const id = line.analysis.id;
        const layer = props.captures?.[id];
        if (last.get(id) === line && layer?.id === CAPTURE_PREFIX + id) {
            own.push({
                layer,
                line,
                tag: null,
                text: "",
                nodes: [],
                capture: id,
            });
        }
        return own;
    });
});
const analyses = computed(() => {
    const found = new Map<string, MapLine>();
    for (const line of [...props.maps].sort((a, b) => a.slot - b.slot)) {
        if (!found.has(line.analysis.id)) found.set(line.analysis.id, line);
    }
    return [...found.values()];
});
const hasFamily = computed(() =>
    entries.value.some((entry) => entry.tag?.family),
);
const grouping = computed<TableGrouping>(() =>
    hasFamily.value ? props.state.grouping : "analysis",
);
const stacked = computed(() => props.state.layout === "stack");
const targets = computed(() =>
    PANE_LETTERS.slice(0, PANES_SHOWN[props.state.layout]),
);
const visible = computed(() => {
    const wanted = foldText(query.value.trim());
    return entries.value.filter((entry) => {
        if (only.value !== null && entry.line.analysis.id !== only.value) {
            return false;
        }
        if (wanted === "") return true;
        return (
            foldText(entry.layer.label).includes(wanted) ||
            foldText(entry.text).includes(wanted)
        );
    });
});
const activeFilters = computed(
    () =>
        Number(query.value.trim() !== "") +
        Number(only.value !== null) +
        Number(grouping.value === "tag"),
);
const filtersName = computed(() =>
    activeFilters.value > 0
        ? interpolate(
              $gettext("Filters, %{n} active"),
              { n: activeFilters.value },
              true,
          )
        : $gettext("Filters"),
);
const hint = computed(() =>
    $gettext(
        "Click: lay in the target pane. Drag: onto any pane. In Stack mode, a click adds or removes the layer.",
    ),
);
const groups = computed<Group[]>(() =>
    grouping.value === "tag"
        ? groupsByTag(visible.value)
        : groupsByAnalysis(visible.value),
);
const order = computed(() =>
    groups.value.flatMap((group) => group.entries.map((e) => e.layer.id)),
);
const stop = computed(() =>
    roving.value && order.value.includes(roving.value)
        ? roving.value
        : order.value[0] ?? null,
);

function pinsOf(group: Group): { slot: number; hue: string }[] {
    return group.node
        ? marks
              .slots(group.node)
              .map(({ slot }) => ({ slot, hue: focusHue(slot) }))
        : [];
}

function canvasCount(n: number): string {
    return interpolate(
        $ngettext("%{n} canvas", "%{n} canvases", n),
        { n },
        true,
    );
}

function groupsByAnalysis(list: Entry[]): Group[] {
    const found = new Map<string, Entry[]>();
    for (const entry of list) {
        const id = entry.line.analysis.id;
        found.set(id, [...(found.get(id) ?? []), entry]);
    }
    return [...found.entries()].map(([id, members]) => {
        const { analysis } = members[0].line;
        const technique = analysis.technique?.label.value;
        return {
            id: `analysis:${id}`,
            title: shortAnalysisName(analysis.name.value),
            fullTitle: analysis.name.value,
            node: analysisNode(id),
            meta: [technique, canvasCount(members.length)]
                .filter(Boolean)
                .join(" · "),
            note: null,
            entries: members,
            compare: false,
        };
    });
}

function familyMeta(family: string, members: Entry[], shared: number): string {
    const parts: string[] = [];
    const [kind, rest] = family.split(":");
    if (kind === "element") {
        const number = atomicNumber(rest.split("+")[0]);
        if (number !== null) {
            parts.push(interpolate($gettext("Z %{z}"), { z: number }, true));
        }
    }
    parts.push(
        interpolate(
            $ngettext("%{n} analysis", "%{n} analyses", shared),
            { n: shared },
            true,
        ),
    );
    parts.push(canvasCount(members.length));
    return parts.join(" · ");
}

function groupsByTag(list: Entry[]): Group[] {
    const families = new Map<string, Entry[]>();
    const kinds = new Map<string, Entry[]>();
    const unclassified: Entry[] = [];
    for (const entry of list) {
        if (!entry.tag) unclassified.push(entry);
        else {
            const target = entry.tag.family ? families : kinds;
            const key = entry.tag.family ?? entry.tag.key;
            target.set(key, [...(target.get(key) ?? []), entry]);
        }
    }
    const spread = (members: Entry[]): number =>
        new Set(members.map((entry) => entry.line.analysis.id)).size;
    const familyGroups = [...families.entries()]
        .sort(
            ([a, aMembers], [b, bMembers]) =>
                Number(spread(bMembers) > 1) - Number(spread(aMembers) > 1) ||
                compareFamilies(a, b),
        )
        .map(
            ([family, members]): Group => ({
                id: `family:${family}`,
                title: members[0].text,
                fullTitle: null,
                node: null,
                meta: familyMeta(family, members, spread(members)),
                note: null,
                entries: members,
                compare: spread(members) > 1,
            }),
        );
    const kindGroups = [...kinds.entries()].map(
        ([key, members]): Group => ({
            id: key,
            title: members[0].text,
            fullTitle: null,
            node: null,
            meta: canvasCount(members.length),
            note: null,
            entries: members,
            compare: false,
        }),
    );
    const rest: Group[] =
        unclassified.length > 0
            ? [
                  {
                      id: "unclassified",
                      fullTitle: null,
                      node: null,
                      title: interpolate(
                          $gettext("Unclassified · %{n}"),
                          { n: unclassified.length },
                          true,
                      ),
                      meta: "",
                      note: unclassified.some((entry) => !entry.capture)
                          ? $gettext(
                                "The canvas has no “Imaging layers” tile: the stored label is shown as is.",
                            )
                          : null,
                      entries: unclassified,
                      compare: false,
                  },
              ]
            : [];
    return [...familyGroups, ...kindGroups, ...rest];
}

/**
 * Deletes a capture and keeps the keyboard where it was: the focus goes to the
 * next thumbnail of its group, else the previous one, else the group's title.
 */
async function deleteCapture(entry: Entry, group: Group): Promise<void> {
    const members = group.entries.filter((member) => member !== entry);
    const index = group.entries.indexOf(entry);
    const neighbour = members[index] ?? members[members.length - 1] ?? null;
    emit("delete-capture", entry.capture ?? "");
    await nextTick();
    const target = neighbour
        ? [
              ...(root.value?.querySelectorAll<HTMLElement>(".layer-thumb") ??
                  []),
          ].find((thumb) => thumb.dataset.canvas === neighbour.layer.id)
        : document.getElementById(`${group.id}-title`);
    target?.focus();
}

function panesOf(canvas: string): string[] {
    return props.state.panes.flatMap((pane, index) =>
        pane === canvas && index < targets.value.length
            ? [PANE_LETTERS[index]]
            : [],
    );
}

function inStack(canvas: string): boolean {
    return (
        stacked.value &&
        props.state.stack.layers.some((layer) => layer.canvas === canvas)
    );
}

function ids(group: Group): string[] {
    return group.entries.map((entry) => entry.layer.id);
}

function pick(canvas: string): void {
    if (stacked.value) emit("toggle-stack", canvas);
    else emit("place", canvas);
}

function placeAll(group: Group): void {
    emit("place-group", ids(group).slice(0, GROUP_PLACE_MAX));
}

function compare(group: Group): void {
    emit("compare", ids(group).slice(0, GROUP_PLACE_MAX));
}

function setGrouping(next: TableGrouping): void {
    if (next === grouping.value) return;
    emit("group-change", next);
}

function toggleAnalysis(id: string | null): void {
    only.value = id;
}

function onKeydown(event: KeyboardEvent): void {
    if (!ROVING_KEYS.has(event.key)) return;
    const next = nextId(order.value, stop.value, event.key);
    if (next === null) return;
    event.preventDefault();
    roving.value = next;
    const button = [...(root.value?.querySelectorAll("button") ?? [])].find(
        (item) => (item as HTMLElement).dataset.canvas === next,
    );
    (button as HTMLElement | undefined)?.focus();
}
</script>

<template>
    <section
        ref="root"
        class="layer-gallery"
        :aria-label="$gettext('Gallery')"
    >
        <div class="head">
            <div class="top">
                <h3 class="title">{{ $gettext("Gallery") }}</h3>
                <span class="head-count">{{
                    canvasCount(entries.length)
                }}</span>
                <HelpTip
                    class="compact-help"
                    :text="hint"
                    align="end"
                    placement="below"
                >
                    <template #default="{ describedby }">
                        <span
                            class="help-chip"
                            tabindex="0"
                            role="img"
                            :aria-label="$gettext('How to use the gallery')"
                            :aria-describedby="describedby"
                        >
                            <svg
                                class="icon"
                                :viewBox="ICON_VIEW_BOX"
                                aria-hidden="true"
                                focusable="false"
                            >
                                <path
                                    v-for="(path, index) in ICONS[
                                        'info-circle'
                                    ]"
                                    :key="index"
                                    :d="path"
                                />
                            </svg>
                        </span>
                    </template>
                </HelpTip>
                <div
                    v-if="!stacked"
                    class="target"
                >
                    <span class="target-text">{{ $gettext("Place in") }}</span>
                    <button
                        v-for="(letter, index) in targets"
                        :key="letter"
                        type="button"
                        class="target-pane"
                        :data-pane="letter.toLowerCase()"
                        :aria-pressed="
                            props.state.active === index ? 'true' : 'false'
                        "
                        @click="emit('set-target', index)"
                    >
                        {{ letter }}
                    </button>
                </div>
            </div>
            <button
                type="button"
                class="filters-toggle"
                :aria-expanded="filtersOpen ? 'true' : 'false'"
                :aria-controls="filtersId"
                :aria-label="filtersName"
                @click="filtersOpen = !filtersOpen"
            >
                <span aria-hidden="true">{{ $gettext("Filters") }}</span>
                <span
                    v-if="activeFilters > 0"
                    class="active-count"
                    aria-hidden="true"
                    >{{ activeFilters }}</span
                >
                <svg
                    class="icon"
                    :viewBox="ICON_VIEW_BOX"
                    aria-hidden="true"
                    focusable="false"
                >
                    <path
                        v-for="(path, index) in ICONS[
                            filtersOpen ? 'chevron-up' : 'chevron-down'
                        ]"
                        :key="index"
                        :d="path"
                    />
                </svg>
            </button>
            <div
                :id="filtersId"
                class="filters"
                :data-open="filtersOpen ? 'true' : 'false'"
            >
                <div class="search">
                    <input
                        v-model="query"
                        class="filter"
                        type="search"
                        :aria-label="$gettext('Filter the layers')"
                        :placeholder="$gettext('Filter by label or tag')"
                    />
                    <svg
                        class="icon"
                        :viewBox="ICON_VIEW_BOX"
                        aria-hidden="true"
                        focusable="false"
                    >
                        <path
                            v-for="(path, index) in ICONS.search"
                            :key="index"
                            :d="path"
                        />
                    </svg>
                </div>
                <div
                    v-if="analyses.length > 1"
                    class="tabs"
                    role="group"
                    :aria-label="$gettext('Analyses')"
                >
                    <button
                        type="button"
                        class="analysis-tab"
                        :aria-pressed="only === null ? 'true' : 'false'"
                        @click="toggleAnalysis(null)"
                    >
                        {{ $gettext("All") }}
                    </button>
                    <span
                        v-for="line in analyses"
                        :key="line.analysis.id"
                        class="analysis"
                        :data-on="only === line.analysis.id ? 'true' : 'false'"
                    >
                        <button
                            type="button"
                            class="analysis-tab"
                            :title="line.analysis.name.value"
                            :aria-pressed="
                                only === line.analysis.id ? 'true' : 'false'
                            "
                            @click="toggleAnalysis(line.analysis.id)"
                        >
                            {{ shortAnalysisName(line.analysis.name.value) }}
                        </button>
                        <button
                            type="button"
                            class="analysis-focus ms-focus"
                            v-bind="marks.focus(analysisNode(line.analysis.id))"
                            :title="
                                interpolate(
                                    $gettext('Focus on %{name}'),
                                    { name: line.analysis.name.value },
                                    true,
                                )
                            "
                            :aria-label="
                                interpolate(
                                    $gettext('Focus on %{name}'),
                                    { name: line.analysis.name.value },
                                    true,
                                )
                            "
                            :aria-pressed="
                                marks.pressed(analysisNode(line.analysis.id))
                            "
                            @click="
                                marks.toggle(analysisNode(line.analysis.id))
                            "
                        >
                            <FocusPip :node="analysisNode(line.analysis.id)" />
                        </button>
                    </span>
                </div>
                <div class="grouping-row">
                    <span class="grouping-label">{{
                        $gettext("Group by")
                    }}</span>
                    <div
                        class="grouping"
                        role="group"
                        :aria-label="$gettext('Group by')"
                    >
                        <button
                            type="button"
                            data-grouping="analysis"
                            :aria-pressed="
                                grouping === 'analysis' ? 'true' : 'false'
                            "
                            @click="setGrouping('analysis')"
                        >
                            {{ $gettext("Analysis") }}
                        </button>
                        <button
                            type="button"
                            data-grouping="tag"
                            :disabled="!hasFamily"
                            :aria-pressed="
                                grouping === 'tag' ? 'true' : 'false'
                            "
                            :title="
                                hasFamily
                                    ? undefined
                                    : $gettext(
                                          'No layer of the Selection has a declared element or band.',
                                      )
                            "
                            @click="setGrouping('tag')"
                        >
                            {{ $gettext("Element or band") }}
                        </button>
                    </div>
                </div>
            </div>
        </div>
        <div class="scroller">
            <div
                class="groups"
                @keydown="onKeydown"
            >
                <p
                    v-if="groups.length === 0"
                    class="empty"
                >
                    {{ $gettext("No layer matches the filter.") }}
                </p>
                <section
                    v-for="group in groups"
                    :key="group.id"
                    class="group"
                    :aria-labelledby="`${group.id}-title`"
                >
                    <header>
                        <span
                            v-if="pinsOf(group).length > 0"
                            class="pins"
                            aria-hidden="true"
                        >
                            <b
                                v-for="pin in pinsOf(group)"
                                :key="pin.slot"
                                :style="{ '--h': pin.hue }"
                                >{{ pin.slot }}</b
                            >
                        </span>
                        <h4
                            :id="`${group.id}-title`"
                            class="group-title"
                            tabindex="-1"
                            :title="group.fullTitle ?? group.note ?? undefined"
                        >
                            {{ group.title }}
                        </h4>
                        <span
                            v-if="group.meta"
                            class="group-meta"
                            >{{ group.meta }}</span
                        >
                        <span class="spacer"></span>
                        <button
                            type="button"
                            class="place-all"
                            @click="placeAll(group)"
                        >
                            {{ $gettext("Place all") }}
                        </button>
                        <button
                            v-if="group.compare"
                            type="button"
                            class="compare"
                            @click="compare(group)"
                        >
                            {{ $gettext("Compare") }}
                        </button>
                    </header>
                    <p
                        v-if="group.note"
                        class="note"
                    >
                        {{ group.note }}
                    </p>
                    <div class="grid">
                        <template
                            v-for="entry in group.entries"
                            :key="entry.layer.id"
                        >
                            <div
                                v-if="entry.capture"
                                class="capture-cell"
                            >
                                <LayerThumb
                                    :canvas="entry.layer.id"
                                    :label="entry.layer.label"
                                    :service="null"
                                    :url="
                                        entry.layer.image.url
                                            ? captureThumbnail(
                                                  entry.layer.image.url,
                                              )
                                            : null
                                    "
                                    :tag="null"
                                    :panes="panesOf(entry.layer.id)"
                                    :in-stack="inStack(entry.layer.id)"
                                    :stop="entry.layer.id === stop"
                                    @pick="pick(entry.layer.id)"
                                />
                                <span class="capture-badge">{{
                                    $gettext("this browser")
                                }}</span>
                                <button
                                    type="button"
                                    class="capture-delete"
                                    :title="$gettext('Delete the capture')"
                                    :aria-label="$gettext('Delete the capture')"
                                    @click="deleteCapture(entry, group)"
                                >
                                    <svg
                                        class="icon"
                                        :viewBox="ICON_VIEW_BOX"
                                        aria-hidden="true"
                                        focusable="false"
                                    >
                                        <path
                                            v-for="(path, index) in ICONS.trash"
                                            :key="index"
                                            :d="path"
                                        />
                                    </svg>
                                </button>
                            </div>
                            <LayerThumb
                                v-else
                                :canvas="entry.layer.id"
                                :label="entry.layer.label"
                                :service="entry.layer.image.service"
                                :tag="entry.tag ? entry.text : null"
                                :panes="panesOf(entry.layer.id)"
                                :in-stack="inStack(entry.layer.id)"
                                :stop="entry.layer.id === stop"
                                :data-rel="
                                    entry.nodes.length > 0
                                        ? marks.rel(entry.nodes)
                                        : undefined
                                "
                                :style="
                                    entry.nodes.length > 0
                                        ? marks.rowStyle(entry.nodes)
                                        : undefined
                                "
                                @pick="pick(entry.layer.id)"
                            />
                        </template>
                    </div>
                </section>
            </div>
        </div>
        <p class="hint">{{ hint }}</p>
    </section>
</template>

<style scoped>
@property --fade {
    syntax: "<length>";
    inherits: false;
    initial-value: 0rem;
}

.layer-gallery {
    container-type: size;
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto;
    min-block-size: 0;
    overflow: hidden;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.625rem;
    background: var(--bg);
}

.layer-gallery .head {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.625rem 0.75rem 0.5rem;
    border-block-end: 0.0625rem solid var(--border-hover);
}

.layer-gallery .top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.375rem;
}

.layer-gallery .head-count {
    flex: 1;
    color: var(--ink-muted);
    font-size: 0.6875rem;
    white-space: nowrap;
}

.layer-gallery .compact-help,
.layer-gallery .filters-toggle {
    display: none;
}

.layer-gallery .help-chip {
    display: inline-grid;
    place-items: center;
    inline-size: 1.25rem;
    block-size: 1.25rem;
    border-radius: 50%;
    color: var(--ink-muted);
    cursor: help;
}

.layer-gallery .help-chip .icon,
.layer-gallery .filters-toggle .icon {
    inline-size: 0.875rem;
    block-size: 0.875rem;
    fill: currentcolor;
}

.layer-gallery .filters {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
}

.layer-gallery .filters-toggle {
    align-items: center;
    gap: 0.375rem;
    align-self: flex-start;
    padding: 0.1875rem 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.4375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
}

.layer-gallery .filters-toggle .active-count {
    display: inline-grid;
    place-items: center;
    min-inline-size: 1rem;
    block-size: 1rem;
    border-radius: 999rem;
    background: var(--ink);
    color: var(--surface);
    font: 600 0.625rem var(--font-mono);
}

.layer-gallery .title {
    margin: 0;
    font: 600 1.0625rem/1.1 var(--font-display);
}

.layer-gallery .target {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: 0.25rem;
    color: var(--ink-muted);
    font-size: 0.71875rem;
}

.layer-gallery .target-pane {
    --pane: var(--pane-a);
    inline-size: 1.5rem;
    block-size: 1.375rem;
    padding: 0;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.3125rem;
    background: var(--surface);
    color: var(--ink-muted);
    font: 600 0.6875rem var(--font-mono);
    cursor: pointer;
}

.layer-gallery .target-pane[data-pane="b"] {
    --pane: var(--pane-b);
}

.layer-gallery .target-pane[data-pane="c"] {
    --pane: var(--pane-c);
}

.layer-gallery .target-pane[data-pane="d"] {
    --pane: var(--pane-d);
}

.layer-gallery .target-pane[aria-pressed="true"] {
    border-color: var(--pane);
    background: var(--pane);
    color: var(--surface);
}

.layer-gallery .search {
    position: relative;
}

.layer-gallery .search .filter {
    inline-size: 100%;
    padding: 0.375rem 1.75rem 0.375rem 0.5625rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.4375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.78125rem;
}

.layer-gallery .search .icon {
    position: absolute;
    inset-block-start: 50%;
    inset-inline-end: 0.5rem;
    inline-size: 0.875rem;
    block-size: 0.875rem;
    translate: 0 -50%;
    fill: var(--ink-muted);
    pointer-events: none;
}

.layer-gallery .tabs {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem;
}

.layer-gallery .analysis {
    display: inline-flex;
    align-items: center;
    max-inline-size: 100%;
    min-inline-size: 0;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
}

.layer-gallery .analysis[data-on="true"] {
    border-color: var(--ink);
    background: var(--ink);
}

.layer-gallery .analysis-tab {
    min-inline-size: 0;
    max-inline-size: 11rem;
    padding: 0.125rem 0.5625rem;
    overflow: hidden;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.71875rem;
    text-overflow: ellipsis;
    white-space: nowrap;
    cursor: pointer;
}

.layer-gallery .analysis-tab[aria-pressed="true"] {
    border-color: var(--ink);
    background: var(--ink);
    color: var(--surface);
}

.layer-gallery .analysis .analysis-tab {
    border: none;
    background: none;
}

.layer-gallery .analysis[data-on="true"] .analysis-tab {
    color: var(--surface);
}

.layer-gallery .analysis .analysis-focus {
    flex: none;
    margin-inline-end: 0.1875rem;
}

.layer-gallery .grouping-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem 0.375rem;
}

.layer-gallery .grouping-label {
    color: var(--ink-muted);
    font-size: 0.6875rem;
}

.layer-gallery .grouping {
    display: inline-flex;
    overflow: hidden;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.4375rem;
    background: var(--surface);
}

.layer-gallery .grouping button {
    padding: 0.25rem 0.5rem;
    border: none;
    border-inline-end: 0.0625rem solid var(--border);
    background: none;
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.75rem;
    white-space: nowrap;
    cursor: pointer;
}

.layer-gallery .grouping button:last-child {
    border-inline-end: none;
}

.layer-gallery .grouping button[aria-pressed="true"] {
    background: var(--ink);
    color: var(--surface);
}

.layer-gallery .grouping button:disabled {
    color: var(--ink-dim);
    cursor: not-allowed;
}

.layer-gallery button:focus-visible,
.layer-gallery .help-chip:focus-visible,
.layer-gallery .filter:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.layer-gallery .analysis-focus {
    position: relative;
    inline-size: 1.125rem;
    block-size: 1.125rem;
    padding: 0;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: radial-gradient(
        circle,
        var(--ink-dim) 0.1875rem,
        var(--surface) 0.25rem
    );
    cursor: pointer;
}

.layer-gallery .scroller {
    min-block-size: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
}

@supports (animation-timeline: scroll()) {
    .layer-gallery .scroller {
        mask-image: linear-gradient(
            to bottom,
            #000 calc(100% - var(--fade)),
            transparent
        );
        animation: scroll-fade linear both;
        animation-timeline: scroll(self block);
    }

    @keyframes scroll-fade {
        0% {
            --fade: 1.75rem;
        }

        92% {
            --fade: 1.75rem;
        }

        100% {
            --fade: 0rem;
        }
    }
}

.layer-gallery .groups {
    display: block;
    padding: 0.25rem 0.75rem 0.75rem;
}

.layer-gallery .group {
    margin-block-start: 0.75rem;
    content-visibility: auto;
    contain-intrinsic-size: auto 8rem;
}

.layer-gallery .group header {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.125rem 0.5rem;
    margin-block-end: 0.375rem;
}

.layer-gallery .group .pins {
    display: inline-flex;
    align-self: center;
    gap: 0.0625rem;
}

.layer-gallery .group .pins b {
    display: grid;
    place-items: center;
    inline-size: 1rem;
    block-size: 1rem;
    border-radius: 50%;
    background: var(--h, var(--ink));
    color: var(--focus-on);
    font: 600 0.625rem var(--font-mono);
}

.layer-gallery .group-title {
    min-inline-size: 0;
    margin: 0;
    overflow: hidden;
    font: 600 0.9375rem/1.1 var(--font-display);
    text-overflow: ellipsis;
    white-space: nowrap;
}

.layer-gallery .group-meta,
.layer-gallery .note,
.layer-gallery .empty {
    margin: 0;
    color: var(--ink-muted);
    font-size: 0.6875rem;
}

.layer-gallery .group .spacer {
    flex: 1;
}

.layer-gallery .group :is(.place-all, .compare) {
    padding: 0;
    border: none;
    background: none;
    color: var(--accent-text);
    font: inherit;
    font-size: 0.6875rem;
    text-decoration: underline;
    text-underline-offset: 0.125rem;
    cursor: pointer;
}

.layer-gallery .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(4.375rem, 1fr));
    gap: 0.375rem;
}

@container (max-height: 26rem) {
    .layer-gallery .head {
        position: relative;
        gap: 0.25rem;
        padding: 0.375rem 0.75rem 0.25rem;
    }

    .layer-gallery .compact-help,
    .layer-gallery .filters-toggle {
        display: inline-flex;
    }

    .layer-gallery .target-text,
    .layer-gallery .hint,
    .layer-gallery .group-meta {
        display: none;
    }

    .layer-gallery .filters[data-open="false"] {
        display: none;
    }

    .layer-gallery .filters[data-open="true"] {
        position: absolute;
        z-index: 2;
        inset-block-start: 100%;
        inset-inline: 0;
        max-block-size: calc(100cqh - 3rem);
        padding: 0.5rem 0.75rem;
        overflow-y: auto;
        border-block-end: 0.0625rem solid var(--border-hover);
        background: var(--bg);
        box-shadow: var(--shadow-md);
    }

    .layer-gallery .groups {
        padding-block: 0 0.5rem;
    }

    .layer-gallery .group {
        margin-block-start: 0.375rem;
    }

    .layer-gallery .group header {
        flex-wrap: nowrap;
        margin-block-end: 0.25rem;
    }

    .layer-gallery .grid {
        grid-template-columns: repeat(auto-fill, minmax(4.5rem, 1fr));
        gap: 0.25rem;
    }

    .layer-gallery :deep(.layer-thumb .picture) {
        aspect-ratio: 1;
    }
}

@container (max-height: 13rem) {
    .layer-gallery .head {
        flex-direction: row;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
    }

    .layer-gallery .top {
        flex: 1;
    }

    .layer-gallery .head-count {
        display: none;
    }
}

@media (prefers-reduced-motion: reduce) {
    .layer-gallery .scroller {
        scroll-behavior: auto;
    }
}

.layer-gallery .hint {
    margin: 0;
    padding: 0.5rem 0.75rem;
    border-block-start: 0.0625rem solid var(--border-hover);
    color: var(--ink-muted);
    font-size: 0.6875rem;
    line-height: 1.5;
}

.layer-gallery
    :deep(
        .layer-thumb:is(
                [data-rel="self"],
                [data-rel="direct"],
                [data-rel="evidence"]
            )
    ) {
    outline: 0.125rem solid var(--h1, var(--focus-1));
    outline-offset: 0.0625rem;
}

.layer-gallery :deep(.layer-thumb[data-rel="evidence"]) {
    outline-width: 0.0625rem;
}

.layer-gallery :deep(.layer-thumb[data-rel="none"]) {
    opacity: 0.45;
}

.layer-gallery .capture-cell {
    position: relative;
    display: grid;
    min-inline-size: 0;
}

.layer-gallery .capture-badge {
    position: absolute;
    inset-block-start: 0.3125rem;
    inset-inline-end: 0.3125rem;
    max-inline-size: calc(100% - 0.625rem);
    padding: 0.0625rem 0.25rem;
    border-radius: 0.1875rem;
    background: color-mix(in srgb, var(--ink) 80%, transparent);
    color: var(--surface);
    font: 500 0.5625rem/1.2 var(--font-mono);
    text-align: end;
}

.layer-gallery .capture-delete {
    position: absolute;
    inset-block-end: 1.5rem;
    inset-inline-end: 0.3125rem;
    display: grid;
    place-items: center;
    inline-size: 1.5rem;
    block-size: 1.5rem;
    padding: 0;
    border: 0;
    border-radius: 0.25rem;
    background: color-mix(in srgb, var(--surface) 90%, transparent);
    color: var(--ink);
    cursor: pointer;
}

.layer-gallery .capture-delete:hover {
    color: var(--blue-text);
}

.layer-gallery .capture-delete .icon {
    inline-size: 0.75rem;
    block-size: 0.75rem;
    fill: currentcolor;
}
</style>
