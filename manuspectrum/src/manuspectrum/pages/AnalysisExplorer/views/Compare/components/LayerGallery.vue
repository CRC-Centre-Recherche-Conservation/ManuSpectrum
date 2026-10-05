<script setup lang="ts">
import { computed, ref, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";
import LayerThumb from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LayerThumb.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { nextId } from "@/manuspectrum/pages/AnalysisExplorer/folio/roving.ts";
import { foldText } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import { tagText } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tag-text.ts";
import {
    compareFamilies,
    layerTag,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";
import {
    analysisNode,
    elementNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { atomicNumber } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/periodic.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LayerTag } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";
import type {
    TableGrouping,
    TableState,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

const PANE_LETTERS = ["A", "B", "C", "D"] as const;
const PANES_SHOWN: Readonly<Record<TableState["layout"], number>> = {
    single: 1,
    curtain: 2,
    grid2: 2,
    grid4: 4,
    stack: 0,
};
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
}

interface Group {
    id: string;
    title: string;
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
 * them (`compare`). The thumbnails are one tab stop.
 */
const props = defineProps<{
    maps: readonly MapLine[];
    state: TableState;
}>();
const emit = defineEmits<{
    place: [canvas: string];
    "toggle-stack": [canvas: string];
    "set-target": [pane: number];
    "group-change": [grouping: TableGrouping];
    "place-group": [canvases: string[]];
    compare: [canvases: string[]];
}>();

const { $gettext, $ngettext, interpolate } = useGettext();
const marks = useLinkedMarks();
const root = useTemplateRef<HTMLElement>("root");

const query = ref("");
const only = ref<string | null>(null);
const roving = ref<string | null>(null);

const entries = computed<Entry[]>(() =>
    [...props.maps]
        .sort((a, b) => a.slot - b.slot)
        .flatMap((line) =>
            line.file.layers.map((layer) => {
                const tag = layerTag(layer);
                return {
                    layer,
                    line,
                    tag,
                    text: tag ? tagText(tag.parts) : "",
                    nodes: layer.elements.flatMap((item) =>
                        item.symbol ? [elementNode(item.symbol)] : [],
                    ),
                };
            }),
        ),
);
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
            title: analysis.name.value,
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
                      title: interpolate(
                          $gettext("Unclassified · %{n}"),
                          { n: unclassified.length },
                          true,
                      ),
                      meta: "",
                      note: $gettext(
                          "The canvas has no “Imaging layers” tile: the stored label is shown as is.",
                      ),
                      entries: unclassified,
                      compare: false,
                  },
              ]
            : [];
    return [...familyGroups, ...kindGroups, ...rest];
}

function panesOf(canvas: string): string[] {
    return props.state.panes.flatMap((pane, index) =>
        pane === canvas && index < PANE_LETTERS.length
            ? [PANE_LETTERS[index]]
            : [],
    );
}

function inStack(canvas: string): boolean {
    return props.state.stack.layers.some((layer) => layer.canvas === canvas);
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
            <h3 class="title">{{ $gettext("Gallery") }}</h3>
            <div class="target">
                <template v-if="stacked">
                    <span>{{ $gettext("Click: add to the stack") }}</span>
                </template>
                <template v-else>
                    <span class="target-text">{{ $gettext("Place in") }}</span>
                    <button
                        v-for="(letter, index) in targets"
                        :key="letter"
                        type="button"
                        class="target-pane"
                        :aria-pressed="
                            props.state.active === index ? 'true' : 'false'
                        "
                        @click="emit('set-target', index)"
                    >
                        {{ letter }}
                    </button>
                </template>
            </div>
            <input
                v-model="query"
                class="filter"
                type="search"
                :aria-label="$gettext('Filter the layers')"
                :placeholder="$gettext('Filter by label or tag')"
            />
            <div
                class="grouping"
                role="group"
                :aria-label="$gettext('Group by')"
            >
                <button
                    type="button"
                    data-grouping="analysis"
                    :aria-pressed="grouping === 'analysis' ? 'true' : 'false'"
                    @click="setGrouping('analysis')"
                >
                    {{ $gettext("Analysis") }}
                </button>
                <button
                    type="button"
                    data-grouping="tag"
                    :disabled="!hasFamily"
                    :aria-pressed="grouping === 'tag' ? 'true' : 'false'"
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
                >
                    <button
                        type="button"
                        class="analysis-tab"
                        :aria-pressed="
                            only === line.analysis.id ? 'true' : 'false'
                        "
                        @click="toggleAnalysis(line.analysis.id)"
                    >
                        {{ line.analysis.name.value }}
                    </button>
                    <button
                        type="button"
                        class="analysis-focus ms-focus"
                        v-bind="marks.focus(analysisNode(line.analysis.id))"
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
                        @click="marks.toggle(analysisNode(line.analysis.id))"
                    >
                        <FocusPip :node="analysisNode(line.analysis.id)" />
                    </button>
                </span>
            </div>
        </div>
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
                    <h4
                        :id="`${group.id}-title`"
                        class="group-title"
                        :title="group.note ?? undefined"
                    >
                        {{ group.title }}
                    </h4>
                    <span
                        v-if="group.meta"
                        class="group-meta"
                        >{{ group.meta }}</span
                    >
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
                    <LayerThumb
                        v-for="entry in group.entries"
                        :key="entry.layer.id"
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
                        @pick="pick(entry.layer.id)"
                    />
                </div>
            </section>
        </div>
    </section>
</template>

<style scoped>
.layer-gallery {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr);
    gap: 0.5rem;
    min-block-size: 0;
}

.layer-gallery .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
}

.layer-gallery .title {
    margin: 0;
    color: var(--ink-muted);
    font: 0.6875rem var(--font-mono);
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.layer-gallery .target,
.layer-gallery .grouping,
.layer-gallery .tabs,
.layer-gallery .analysis {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.75rem;
}

.layer-gallery button:not(.analysis-focus) {
    padding: 0.125rem 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
}

.layer-gallery button[aria-pressed="true"] {
    border-color: var(--ink);
    background: var(--ink);
    color: var(--surface);
}

.layer-gallery button:disabled {
    color: var(--ink-dim);
    cursor: not-allowed;
}

.layer-gallery button:focus-visible,
.layer-gallery .filter:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.layer-gallery .analysis-focus {
    position: relative;
    inline-size: 1.25rem;
    block-size: 1.25rem;
    padding: 0;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    cursor: pointer;
}

.layer-gallery .filter {
    flex: 1;
    min-inline-size: 8rem;
    padding: 0.125rem 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.75rem;
}

.layer-gallery .groups {
    display: grid;
    align-content: start;
    gap: 0.75rem;
    min-block-size: 0;
    overflow-y: auto;
}

.layer-gallery .group {
    content-visibility: auto;
    contain-intrinsic-size: auto 8rem;
}

.layer-gallery .group header {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.5rem;
    margin-block-end: 0.25rem;
}

.layer-gallery .group-title {
    margin: 0;
    font-size: 0.8125rem;
}

.layer-gallery .group-meta,
.layer-gallery .note,
.layer-gallery .empty {
    margin: 0;
    color: var(--ink-muted);
    font-size: 0.6875rem;
}

.layer-gallery .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(4.5rem, 1fr));
    gap: 0.375rem;
}

.layer-gallery :deep(.layer-thumb[data-rel="none"]) {
    opacity: 0.45;
}
</style>
