<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, shallowRef, watch } from "vue";
import { useGettext } from "vue3-gettext";

import CurtainPane from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/CurtainPane.vue";
import ImagingPane from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ImagingPane.vue";
import LayerGallery from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LayerGallery.vue";
import LayerStack from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LayerStack.vue";

import { useWindowActions } from "@/manuspectrum/pages/AnalysisExplorer/composables/useWindowActions.ts";
import {
    ANNOUNCE_KEY,
    LINKED_SELECTION_KEY,
    WINDOW_FRAME_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { followElement } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/follow-focus.ts";
import { layGroup } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/group-actions.ts";
import {
    applyFiltersToAll,
    canStack,
    defaultState,
    linkedGroups,
    moveInStack,
    NEUTRAL_FILTERS,
    PANE_COUNT,
    PANES_SHOWN,
    place,
    reconcile,
    setActive,
    setFilters,
    setGrouping,
    setLayout,
    setLinkAll,
    setOpacity,
    setTint,
    setVisible,
    stepPane,
    swap,
    toggleInStack,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import { parseNodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import {
    writeImaging,
    readImaging,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";
import {
    sameSize,
    scaleNotes,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";
import {
    galleryOpensWith,
    galleryPlace,
    shownLayout,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/table-frame.ts";
import {
    restoreState,
    storedOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/table-memory.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    PaneFilters,
    TableGrouping,
    TableLayout,
    TableState,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { NormalisedView } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-sync.ts";
import type { ServedSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";
import type { TableFrame } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/table-frame.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

type Side = 0 | 1;

const PERSIST_DELAY_MS = 400;
const PANE_LETTERS = ["A", "B", "C", "D"] as const;
const DEFAULT_FRAME: TableFrame = {
    size: "M",
    enlarged: false,
    phone: false,
};

/**
 * The body of the imaging window: the light table. It owns the table's state
 * (`light-table.ts`) and its parts only emit what the reader does: one to
 * four `ImagingPane`s, a `CurtainPane` between any two canvases, a
 * `LayerStack`, and the `LayerGallery` of every canvas of the Selection. The
 * window's size decides what is drawn (`table-frame.ts`): one pane in S,
 * four folded to two and the gallery below the table in M, the gallery to
 * the right in L and enlarged. The table keeps its layout in the browser
 * (`table-memory.ts`, `writeImaging`) after a pause and on closing, and
 * follows the Selection (`reconcile`). Zoom and pan of the panes of one
 * analysis (or of all, `linkAll`) are relayed here from the pane moved, and a
 * relayed view is dropped when its pane changes canvas; the
 * sizes the panes are served at give the scale notes. The focus only
 * styles; « Follow the focus », off until the reader turns it on and never
 * stored, moves the panes onto the layer of an element newly pinned.
 */
const props = defineProps<{
    maps: readonly MapLine[];
    windowId: string;
}>();

const { $gettext, interpolate } = useGettext();
const announce = inject(ANNOUNCE_KEY, () => undefined);
const linked = inject(LINKED_SELECTION_KEY, null);
const frameRef = inject(WINDOW_FRAME_KEY, ref(DEFAULT_FRAME));

const state = ref<TableState>(restoreState(readImaging(), props.maps));
const sizes = shallowRef<ReadonlyMap<string, ServedSize | null>>(new Map());
const views = shallowRef<(NormalisedView | null)[]>(
    Array(PANE_COUNT).fill(null),
);
const followFocus = ref(false);
const notice = ref("");
const galleryOpen = ref(
    galleryOpensWith(frameRef.value, analysisCount(props.maps)),
);

const analysisIds = computed(() => [
    ...new Set(props.maps.map((line) => line.analysis.id)),
]);
const frame = computed(() => frameRef.value);
const small = computed(() => !frame.value.enlarged && frame.value.size === "S");
const shown = computed(() => shownLayout(state.value.layout, frame.value));
const shownCount = computed(() => PANES_SHOWN[shown.value]);
const shownState = computed<TableState>(() => ({
    ...state.value,
    layout: shown.value,
    active: Math.min(state.value.active, Math.max(shownCount.value - 1, 0)),
}));
const galleryAt = computed(() => galleryPlace(frame.value, galleryOpen.value));
const byCanvas = computed(
    () =>
        new Map(
            props.maps.flatMap((line) =>
                line.file.layers.map(
                    (layer) => [layer.id, { layer, line }] as const,
                ),
            ),
        ),
);
const notes = computed(() =>
    scaleNotes(shownState.value, props.maps, sizes.value),
);
const paneIndexes = computed(() =>
    Array.from({ length: shownCount.value }, (_, pane) => pane),
);
const canLinkAll = computed(() => analysisIds.value.length > 1);
const canSwap = computed(
    () => !small.value && ["curtain", "grid2", "grid4"].includes(shown.value),
);
const phone = computed(() => frame.value.phone);
const layoutChoices = computed(() =>
    allChoices.value.filter(
        (choice) =>
            !phone.value ||
            ["single", "curtain", "stack"].includes(choice.layout),
    ),
);
const allChoices = computed(() => [
    { layout: "single" as const, text: "1", name: $gettext("One pane") },
    {
        layout: "curtain" as const,
        text: $gettext("Curtain"),
        name: $gettext("Curtain"),
    },
    { layout: "grid2" as const, text: "2", name: $gettext("Two panes") },
    { layout: "grid4" as const, text: "4", name: $gettext("Four panes") },
    {
        layout: "stack" as const,
        text: $gettext("Stack"),
        name: $gettext("Stack"),
    },
]);
const linkTitle = computed(() =>
    canLinkAll.value
        ? $gettext(
              "Link zoom and pan between analyses. Within one analysis they are linked already.",
          )
        : $gettext(
              "Zoom and pan are always linked within one analysis, and there is no other analysis to link.",
          ),
);
const persisted = computed(() => JSON.stringify(storedOf(state.value)));

useWindowActions(() => [
    {
        id: "gallery",
        icon: "image",
        label: $gettext("Gallery"),
        description: $gettext("Show or hide the gallery of every map"),
        pressed: galleryOpen.value && !small.value,
        disabled: small.value,
        run: toggleGallery,
    },
    {
        id: "rearrange",
        icon: "th-large",
        label: $gettext("Rearrange the table"),
        description: $gettext("Lay the table out again from the Selection"),
        run: rearrange,
    },
]);

let persistTimer: ReturnType<typeof setTimeout> | null = null;
let dirty = false;

watch(
    () => props.maps,
    (maps) => {
        state.value = reconcile(state.value, maps);
    },
);
watch(
    () => state.value.panes,
    (now, before) => {
        if (now.every((canvas, pane) => canvas === before[pane])) return;
        const next = [...views.value];
        now.forEach((canvas, pane) => {
            if (canvas !== before[pane]) next[pane] = null;
        });
        views.value = next;
    },
);
watch(persisted, () => {
    dirty = true;
    if (persistTimer !== null) clearTimeout(persistTimer);
    persistTimer = setTimeout(flushPersist, PERSIST_DELAY_MS);
});
watch(
    () => [frame.value.size, frame.value.enlarged],
    () => {
        galleryOpen.value = galleryOpensWith(
            frame.value,
            analysisIds.value.length,
        );
    },
);
watch(notes, (now, before) => {
    if (shown.value === "curtain") return;
    for (const [canvas, note] of now) {
        const had = before.get(canvas);
        if (
            had &&
            sameSize(had.size, note.size) &&
            had.against === note.against
        )
            continue;
        announce(
            interpolate(
                $gettext(
                    "%{label} is at a different scale from %{against} (%{size} against %{reference})",
                ),
                {
                    label: labelOf(canvas),
                    against: labelOf(note.against),
                    size: `${note.size.w} × ${note.size.h} px`,
                    reference: `${note.againstSize.w} × ${note.againstSize.h} px`,
                },
            ),
        );
    }
});
watch(
    () => linked?.selection.value ?? [],
    (now, before) => {
        if (!followFocus.value) return;
        for (const id of now.filter((node) => !before.includes(node))) {
            const parsed = parseNodeId(id);
            const symbol = parsed?.kind === "el" ? parsed.parts[0] : null;
            if (symbol) follow(symbol);
        }
    },
);

onBeforeUnmount(flushPersist);

function analysisCount(maps: readonly MapLine[]): number {
    return new Set(maps.map((line) => line.analysis.id)).size;
}

function flushPersist(): void {
    if (persistTimer !== null) clearTimeout(persistTimer);
    persistTimer = null;
    if (!dirty) return;
    dirty = false;
    writeImaging(storedOf(state.value));
}

function labelOf(canvas: string | null): string {
    const layer: FileLayer | undefined = canvas
        ? byCanvas.value.get(canvas)?.layer
        : undefined;
    return layer?.label || canvas || "";
}

/** Takes the new state; a notice stays only until the next change. */
function apply(next: TableState, message?: string): void {
    if (next === state.value) return;
    state.value = next;
    notice.value = "";
    if (message) announce(message);
}

function refuse(canvas: string): void {
    const message = interpolate(
        $gettext(
            "A stack holds the layers of one analysis: %{label} is not added",
        ),
        { label: labelOf(canvas) },
    );
    notice.value = message;
    announce(message);
}

function layoutName(layout: TableLayout): string {
    return (
        layoutChoices.value.find((choice) => choice.layout === layout)?.name ??
        layout
    );
}

function onLayout(layout: TableLayout): void {
    if (
        small.value ||
        !layoutChoices.value.some((c) => c.layout === layout) ||
        layout === state.value.layout
    )
        return;
    const next = setLayout(state.value, layout, props.maps);
    apply(
        setActive(
            next,
            Math.min(next.active, Math.max(PANES_SHOWN[layout] - 1, 0)),
        ),
        interpolate($gettext("Layout: %{layout}"), {
            layout: layoutName(layout),
        }),
    );
}

function onSwap(): void {
    if (!canSwap.value) return;
    apply(swap(state.value), $gettext("Panes A and B swapped"));
}

function onLinkAll(): void {
    if (!canLinkAll.value) return;
    const on = !state.value.linkAll;
    apply(
        setLinkAll(state.value, on),
        on
            ? $gettext("Zoom and pan linked across analyses")
            : $gettext("Zoom and pan linked within each analysis only"),
    );
}

function onFollowFocus(): void {
    followFocus.value = !followFocus.value;
    announce(
        followFocus.value
            ? $gettext("Following the focus: on")
            : $gettext("Following the focus: off"),
    );
}

function follow(symbol: string): void {
    const next = followElement(shownState.value, symbol, props.maps);
    if (next === shownState.value) return;
    apply(
        { ...state.value, panes: next.panes },
        interpolate(
            $gettext("Following the focus: panes moved to %{element}"),
            {
                element: symbol,
            },
        ),
    );
}

function toggleGallery(): void {
    if (small.value) return;
    galleryOpen.value = !galleryOpen.value;
    announce(
        galleryOpen.value
            ? $gettext("Gallery shown")
            : $gettext("Gallery hidden"),
    );
}

function rearrange(): void {
    state.value = defaultState(props.maps);
    notice.value = "";
    views.value = Array(PANE_COUNT).fill(null);
    announce($gettext("Table laid out again from the Selection"));
}

function onSizeRead(payload: { canvas: string; size: ServedSize }): void {
    sizes.value = new Map(sizes.value).set(payload.canvas, payload.size);
}

function onViewChanged(pane: number, view: NormalisedView): void {
    const next = [...views.value];
    for (const group of linkedGroups(shownState.value, props.maps)) {
        if (!group.includes(pane)) continue;
        for (const other of group) {
            if (other !== pane) next[other] = view;
        }
    }
    views.value = next;
}

function onPair(pane: number, canvas: string): void {
    if (shown.value === "single") {
        const curtain = setLayout(
            {
                ...state.value,
                panes: [state.value.panes[pane], canvas, null, null],
            },
            "curtain",
            props.maps,
        );
        apply(curtain, $gettext("Layout: Curtain"));
        return;
    }
    const other = (pane + 1) % Math.max(shownCount.value, 1);
    apply(place(state.value, canvas, other));
}

function onPaneStep(pane: number, step: 1 | -1): void {
    apply(stepPane(state.value, pane, step, props.maps));
}

function onFilters(index: number, filters: Partial<PaneFilters>): void {
    apply(setFilters(state.value, index, filters));
}

function onFiltersReset(index: number): void {
    apply(setFilters(state.value, index, { ...NEUTRAL_FILTERS }));
}

function onFiltersApplyAll(index: number): void {
    apply(applyFiltersToAll(state.value, index));
}

function onToggleStack(canvas: string): void {
    const next = toggleInStack(state.value, canvas, props.maps);
    if (next === state.value) refuse(canvas);
    else apply(next);
}

function onPlaceGroup(canvases: string[]): void {
    if (state.value.layout !== "stack") {
        apply(layGroup(state.value, canvases, props.maps));
        return;
    }
    let next = state.value;
    let refused: string | null = null;
    for (const canvas of canvases) {
        if (next.stack.layers.some((layer) => layer.canvas === canvas))
            continue;
        if (canStack(next, canvas, props.maps)) {
            next = toggleInStack(next, canvas, props.maps);
        } else refused = canvas;
    }
    apply(next);
    if (refused !== null) refuse(refused);
}

function onCompare(canvases: string[]): void {
    apply(layGroup(state.value, canvases, props.maps));
}

function onCurtainPlace(payload: { pane: Side; canvas: string }): void {
    apply(place(state.value, payload.canvas, payload.pane));
}

function onGrouping(grouping: TableGrouping): void {
    apply(setGrouping(state.value, grouping));
}
</script>

<template>
    <section
        class="light-table"
        :aria-label="$gettext('Imaging light table')"
        :data-size="frame.enlarged ? 'enlarged' : frame.size ?? 'M'"
        :data-shown="shown"
        :data-gallery="galleryAt"
    >
        <div
            class="toolbar"
            role="toolbar"
            :aria-label="$gettext('Light table')"
        >
            <div
                class="segment"
                role="group"
                :aria-label="$gettext('Layout')"
            >
                <button
                    v-for="choice in layoutChoices"
                    :key="choice.layout"
                    type="button"
                    :data-layout="choice.layout"
                    :aria-label="choice.name"
                    :aria-pressed="
                        state.layout === choice.layout ? 'true' : 'false'
                    "
                    :aria-disabled="small ? 'true' : undefined"
                    @click="onLayout(choice.layout)"
                >
                    <span>{{ choice.text }}</span>
                </button>
            </div>
            <button
                v-if="canSwap"
                type="button"
                class="toggle"
                data-action="swap"
                :title="$gettext('Exchange the maps of A and B')"
                @click="onSwap"
            >
                <span>{{ $gettext("Swap A/B") }}</span>
            </button>
            <button
                type="button"
                class="toggle"
                data-action="link-all"
                :title="linkTitle"
                :aria-pressed="state.linkAll ? 'true' : 'false'"
                :aria-disabled="canLinkAll ? undefined : 'true'"
                @click="onLinkAll"
            >
                <span>{{ $gettext("Link zoom across analyses") }}</span>
            </button>
            <button
                type="button"
                class="toggle"
                data-action="follow-focus"
                :title="
                    $gettext(
                        'When an element is pinned in the focus, move the panes onto that element\'s layer.',
                    )
                "
                :aria-pressed="followFocus ? 'true' : 'false'"
                @click="onFollowFocus"
            >
                <span>{{ $gettext("Follow the focus") }}</span>
            </button>
        </div>
        <p
            v-if="notice"
            class="notice"
            role="status"
        >
            <span>{{ notice }}</span>
        </p>
        <div class="body">
            <div class="stage">
                <LayerStack
                    v-if="shown === 'stack'"
                    :stack="state.stack"
                    :maps="props.maps"
                    :filters="state.filters[PANE_COUNT]"
                    :notes="notes"
                    @add="onToggleStack"
                    @remove="onToggleStack"
                    @move="
                        apply(moveInStack(state, $event.canvas, $event.step))
                    "
                    @set-visible="
                        apply(setVisible(state, $event.canvas, $event.on))
                    "
                    @set-opacity="
                        apply(setOpacity(state, $event.canvas, $event.opacity))
                    "
                    @set-tint="
                        apply(setTint(state, $event.canvas, $event.tint))
                    "
                    @size-read="onSizeRead"
                    @filters-change="onFilters(PANE_COUNT, $event)"
                    @filters-reset="onFiltersReset(PANE_COUNT)"
                    @filters-apply-all="onFiltersApplyAll(PANE_COUNT)"
                />
                <CurtainPane
                    v-else-if="shown === 'curtain'"
                    :canvas-a="state.panes[0]"
                    :canvas-b="state.panes[1]"
                    :maps="props.maps"
                    :filters-a="state.filters[0]"
                    :filters-b="state.filters[1]"
                    :scale-note="
                        state.panes[1]
                            ? notes.get(state.panes[1]) ?? null
                            : null
                    "
                    @size-read="onSizeRead"
                    @place="onCurtainPlace"
                    @activate="apply(setActive(state, $event))"
                    @filters-change="onFilters($event.pane, $event.filters)"
                    @filters-reset="onFiltersReset"
                    @filters-apply-all="onFiltersApplyAll"
                />
                <div
                    v-else
                    class="panes"
                >
                    <ImagingPane
                        v-for="pane in paneIndexes"
                        :key="pane"
                        :canvas="state.panes[pane]"
                        :maps="props.maps"
                        :letter="PANE_LETTERS[pane]"
                        :active="shownState.active === pane"
                        :filters="state.filters[pane]"
                        :view="views[pane]"
                        :scale-note="
                            state.panes[pane]
                                ? notes.get(state.panes[pane] as string) ?? null
                                : null
                        "
                        @view-changed="onViewChanged(pane, $event)"
                        @size-read="onSizeRead"
                        @place="apply(place(state, $event, pane))"
                        @step="onPaneStep(pane, $event)"
                        @pair="onPair(pane, $event)"
                        @activate="apply(setActive(state, pane))"
                        @filters-change="onFilters(pane, $event)"
                        @filters-reset="onFiltersReset(pane)"
                        @filters-apply-all="onFiltersApplyAll(pane)"
                    />
                </div>
            </div>
            <LayerGallery
                v-if="galleryAt !== 'hidden'"
                class="gallery"
                :maps="props.maps"
                :state="shownState"
                @place="apply(place(state, $event, shownState.active))"
                @toggle-stack="onToggleStack"
                @set-target="apply(setActive(state, $event))"
                @group-change="onGrouping"
                @place-group="onPlaceGroup"
                @compare="onCompare"
            />
        </div>
    </section>
</template>

<style scoped>
.light-table {
    --table-block-size: 20rem;
    display: grid;
    gap: 0.5rem;
    min-inline-size: 0;
}

.light-table[data-size="L"] {
    --table-block-size: 30rem;
}

.light-table[data-size="enlarged"] {
    --table-block-size: min(70vh, 44rem);
}

.light-table .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
}

.light-table .segment {
    display: flex;
    gap: 0.125rem;
}

.light-table .segment button,
.light-table .toggle {
    min-block-size: var(--explorer-target, 2rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font-size: 0.8125rem;
    cursor: pointer;
}

.light-table .segment button[aria-pressed="true"],
.light-table .toggle[aria-pressed="true"] {
    border-color: var(--ink);
    background: var(--ink);
    color: var(--surface);
}

.light-table [aria-disabled="true"] {
    opacity: 0.5;
    cursor: default;
}

.light-table button:focus-visible {
    outline: 0.125rem solid var(--focus-ring, currentcolor);
    outline-offset: 0.125rem;
}

.light-table .notice {
    margin: 0;
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.light-table .body {
    display: grid;
    gap: 0.5rem;
    min-inline-size: 0;
}

.light-table[data-gallery="right"] .body {
    grid-template-columns: minmax(0, 1fr) 18rem;
}

.light-table .stage {
    display: grid;
    block-size: var(--table-block-size);
    min-inline-size: 0;
    min-block-size: 0;
    background: var(--stage);
}

.light-table .panes {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.5rem;
    min-block-size: 0;
}

.light-table[data-shown="grid2"] .panes {
    grid-template-columns: repeat(2, minmax(0, 1fr));
}

.light-table[data-shown="grid4"] .panes {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    grid-template-rows: repeat(2, minmax(0, 1fr));
}

.light-table .gallery {
    max-block-size: var(--table-block-size);
    overflow: auto;
}

.light-table[data-gallery="strip"] .gallery {
    block-size: 7rem;
    max-block-size: 7rem;
    overflow-x: auto;
    overflow-y: hidden;
}

.light-table[data-gallery="strip"] .gallery :deep(.head),
.light-table[data-gallery="strip"] .gallery :deep(.tabs) {
    display: none;
}

.light-table[data-gallery="strip"] .gallery :deep(.groups) {
    display: flex;
    gap: 0.75rem;
}

.light-table[data-gallery="strip"] .gallery :deep(.grid) {
    grid-auto-flow: column;
    grid-template-columns: none;
    grid-auto-columns: 4.5rem;
}

@media (max-width: 48rem) {
    .light-table[data-shown="grid2"] .panes {
        grid-template-columns: minmax(0, 1fr);
    }

    .light-table[data-gallery="right"] .body {
        grid-template-columns: minmax(0, 1fr);
    }
}
</style>
