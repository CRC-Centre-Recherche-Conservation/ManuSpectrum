<script setup lang="ts">
import { useResizeObserver } from "@vueuse/core";
import {
    computed,
    inject,
    onBeforeUnmount,
    ref,
    shallowRef,
    useTemplateRef,
    watch,
} from "vue";
import { useGettext } from "vue3-gettext";

import CurtainPane from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/CurtainPane.vue";
import ImagingPane from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ImagingPane.vue";
import LayerGallery from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LayerGallery.vue";
import LayerStack from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LayerStack.vue";
import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import { useWindowActions } from "@/manuspectrum/pages/AnalysisExplorer/composables/useWindowActions.ts";
import {
    ANNOUNCE_KEY,
    WINDOW_FRAME_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
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
    setSyncViews,
    setOpacity,
    setTint,
    setVisible,
    stepPane,
    swap,
    toggleInStack,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
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
    isMultiPane,
    shownLayout,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/table-frame.ts";
import {
    restoreState,
    storedOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/table-memory.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { IconName } from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
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
 * window's size decides what is drawn (`table-frame.ts`): the layout the
 * reader chose at any size (one pane in S and, for the two grids, on a phone,
 * where their buttons are disabled), the gallery in a panel to the right of
 * the table that a rail on its edge shows or hides (open by default when the
 * window holds the table and the gallery, a strip under the table on a
 * phone). The table keeps its layout and the choice about the gallery in the
 * browser (`table-memory.ts`, `writeImaging`) after a pause and on closing, and
 * follows the Selection (`reconcile`). Zoom and pan are relayed here from the
 * pane moved to every other shown pane only while the sync toggle
 * (`syncViews`, off by default, stored) is on, whatever the analyses, and a
 * relayed view is dropped when its pane changes canvas; the
 * sizes the panes are served at give the scale notes. The focus only
 * styles.
 */
const props = defineProps<{
    maps: readonly MapLine[];
    windowId: string;
}>();

const { $gettext, interpolate } = useGettext();
const announce = inject(ANNOUNCE_KEY, () => undefined);
const frameRef = inject(WINDOW_FRAME_KEY, ref(DEFAULT_FRAME));

const stored = readImaging();
const state = ref<TableState>(restoreState(stored, props.maps));
const root = useTemplateRef<HTMLElement>("root");
const width = ref<number | null>(null);
const galleryChoice = ref<boolean | null>(stored?.gallery ?? null);
const sizes = shallowRef<ReadonlyMap<string, ServedSize | null>>(new Map());
const views = shallowRef<(NormalisedView | null)[]>(
    Array(PANE_COUNT).fill(null),
);
const notice = ref("");

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
const galleryOpen = computed(
    () =>
        galleryChoice.value ??
        galleryOpensWith(
            frame.value,
            analysisIds.value.length,
            width.value === null ? null : width.value / rem(),
        ),
);
const galleryAt = computed(() => galleryPlace(frame.value, galleryOpen.value));
const railed = computed(() => !frame.value.phone);
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
const canSwap = computed(() => ["curtain", "grid2"].includes(shown.value));
const phone = computed(() => frame.value.phone);
const layoutChoices = computed<
    {
        layout: TableLayout;
        icon: IconName;
        text: string;
        name: string;
        word?: boolean;
        unavailable: string | null;
    }[]
>(() =>
    allChoices.value.map((choice) => ({
        ...choice,
        unavailable: unavailableBecause(choice.layout),
    })),
);
const allChoices = computed<
    {
        layout: TableLayout;
        icon: IconName;
        text: string;
        name: string;
        word?: boolean;
    }[]
>(() => [
    {
        layout: "single",
        icon: "stop",
        text: "1",
        name: $gettext("One pane"),
    },
    {
        layout: "curtain",
        icon: "arrows-h",
        text: $gettext("Curtain"),
        name: $gettext("Curtain"),
        word: true,
    },
    {
        layout: "grid2",
        icon: "two-columns",
        text: "2",
        name: $gettext("Two panes"),
    },
    {
        layout: "grid4",
        icon: "th-large",
        text: "4",
        name: $gettext("Four panes"),
    },
    {
        layout: "stack",
        icon: "clone",
        text: $gettext("Stack"),
        name: $gettext("Stack"),
        word: true,
    },
]);
const persisted = computed(() =>
    JSON.stringify(storedOf(state.value, galleryChoice.value)),
);
const galleryName = computed(() =>
    galleryOpen.value
        ? $gettext("Hide the gallery")
        : $gettext("Show the gallery"),
);

useResizeObserver(root, (entries) => {
    const box = entries[0]?.contentRect;
    if (box && box.width > 0) width.value = box.width;
});

useWindowActions(() => [
    ...(phone.value
        ? [
              {
                  id: "gallery",
                  icon: "image" as const,
                  label: $gettext("Gallery"),
                  description: $gettext(
                      "Show or hide the gallery of every map",
                  ),
                  pressed: galleryOpen.value && !small.value,
                  disabled: small.value,
                  run: toggleGallery,
              },
          ]
        : []),
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
                true,
            ),
        );
    }
});
onBeforeUnmount(flushPersist);

function rem(): number {
    return (
        parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
    );
}

/** Why a layout cannot be chosen in this frame, or null. */
function unavailableBecause(layout: TableLayout): string | null {
    if (small.value) {
        return $gettext("The layouts need a window larger than S");
    }
    if (phone.value && isMultiPane(layout)) {
        return $gettext("Several panes side by side need a wider screen");
    }
    return null;
}

function flushPersist(): void {
    if (persistTimer !== null) clearTimeout(persistTimer);
    persistTimer = null;
    if (!dirty) return;
    dirty = false;
    writeImaging(storedOf(state.value, galleryChoice.value));
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
        true,
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
    if (unavailableBecause(layout) !== null || layout === state.value.layout)
        return;
    const next = setLayout(state.value, layout, props.maps);
    apply(
        setActive(
            next,
            Math.min(next.active, Math.max(PANES_SHOWN[layout] - 1, 0)),
        ),
        interpolate(
            $gettext("Layout: %{layout}"),
            {
                layout: layoutName(layout),
            },
            true,
        ),
    );
}

function onSwap(): void {
    if (!canSwap.value) return;
    apply(swap(state.value), $gettext("Panes A and B swapped"));
}

function onSyncViews(): void {
    const on = !state.value.syncViews;
    apply(
        setSyncViews(state.value, on),
        on
            ? $gettext("Zoom and pan synced across panes")
            : $gettext("Zoom and pan no longer synced"),
    );
}

function toggleGallery(): void {
    if (phone.value && small.value) return;
    galleryChoice.value = !galleryOpen.value;
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
        ref="root"
        class="light-table"
        :aria-label="$gettext('Imaging light table')"
        :data-size="frame.enlarged ? 'enlarged' : frame.size ?? 'M'"
        :data-shown="shown"
        :data-gallery="galleryAt"
        :data-rail="railed ? 'true' : undefined"
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
                    :title="choice.unavailable ?? undefined"
                    :aria-pressed="
                        (phone ? shown : state.layout) === choice.layout
                            ? 'true'
                            : 'false'
                    "
                    :aria-disabled="choice.unavailable ? 'true' : undefined"
                    @click="onLayout(choice.layout)"
                >
                    <svg
                        class="icon"
                        :viewBox="ICON_VIEW_BOX"
                        aria-hidden="true"
                        focusable="false"
                    >
                        <path
                            v-for="(path, index) in ICONS[choice.icon]"
                            :key="index"
                            :d="path"
                        />
                    </svg>
                    <span :class="{ word: choice.word }">{{
                        choice.text
                    }}</span>
                </button>
            </div>
            <IconButton
                v-if="!small"
                icon="link"
                data-action="sync-views"
                :label="$gettext('Sync zoom and pan across panes')"
                :pressed="state.syncViews"
                @click="onSyncViews"
            />
            <button
                v-if="canSwap"
                type="button"
                class="swap"
                data-action="swap"
                :title="$gettext('Exchange the maps of A and B')"
                @click="onSwap"
            >
                <svg
                    class="icon"
                    :viewBox="ICON_VIEW_BOX"
                    aria-hidden="true"
                    focusable="false"
                >
                    <path
                        v-for="(path, index) in ICONS['arrow-right-arrow-left']"
                        :key="index"
                        :d="path"
                    />
                </svg>
                <span class="word">{{ $gettext("Swap A/B") }}</span>
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
                    :active="shownState.active"
                    :scale-note="
                        state.panes[1]
                            ? notes.get(state.panes[1]) ?? null
                            : null
                    "
                    @size-read="onSizeRead"
                    @place="onCurtainPlace"
                    @step="onPaneStep($event.pane, $event.delta)"
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
            <button
                v-if="railed"
                type="button"
                class="rail"
                data-action="gallery-rail"
                :aria-expanded="galleryOpen ? 'true' : 'false'"
                :aria-label="galleryName"
                :title="galleryName"
                @click="toggleGallery"
            >
                <span
                    class="arrow"
                    aria-hidden="true"
                    >{{ galleryOpen ? "›" : "‹" }}</span
                >
            </button>
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
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    block-size: 100%;
    min-inline-size: 0;
    min-block-size: 0;
}

.light-table .toolbar {
    display: flex;
    flex: none;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 0.75rem;
}

.light-table .segment {
    display: inline-flex;
    overflow: hidden;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.5rem;
    background: var(--surface);
}

.light-table .segment button {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-block-size: var(--explorer-target, 2rem);
    padding-inline: 0.625rem;
    border: none;
    border-inline-end: 0.0625rem solid var(--border);
    background: transparent;
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.8125rem;
    white-space: nowrap;
    cursor: pointer;
}

.light-table .segment button:last-child {
    border-inline-end: none;
}

.light-table .segment button:hover {
    background: var(--bg-alt);
    color: var(--ink);
}

.light-table .segment button[aria-pressed="true"] {
    background: var(--ink);
    color: var(--surface);
}

.light-table .icon {
    flex: none;
    inline-size: 1rem;
    block-size: 1rem;
    fill: currentColor;
}

.light-table .swap {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-block-size: var(--explorer-target, 2rem);
    padding-inline: 0.625rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.5rem;
    background: var(--surface);
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
}

.light-table .swap:hover {
    background: var(--bg-alt);
    color: var(--ink);
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
    flex: none;
    margin: 0;
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.light-table .body {
    display: grid;
    flex: 1 1 0;
    grid-template-rows: minmax(0, 1fr);
    gap: 0.5rem;
    min-inline-size: 0;
    min-block-size: 0;
}

.light-table[data-rail="true"] .body {
    grid-template-columns: minmax(0, 1fr) 1.75rem;
}

.light-table[data-rail="true"][data-gallery="right"] .body {
    grid-template-columns: minmax(10rem, 1fr) 1.75rem minmax(0, 18.5rem);
}

.light-table[data-gallery="strip"] .body {
    grid-template-rows: minmax(8rem, 1fr) minmax(0, 7rem);
}

.light-table .rail {
    display: grid;
    place-items: center;
    padding: 0;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.5rem;
    background: var(--surface);
    color: var(--ink-muted);
    font: inherit;
    font-size: 1.125rem;
    line-height: 1;
    cursor: pointer;
}

.light-table .rail:hover {
    background: var(--bg-alt);
    color: var(--ink);
}

.light-table .stage {
    isolation: isolate;
    display: grid;
    min-inline-size: 0;
    min-block-size: 8rem;
    padding: 0.125rem;
    border-radius: 0.625rem;
    background: var(--stage);
}

.light-table .panes {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr);
    gap: 0.125rem;
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
    min-block-size: 0;
    overflow: auto;
}

.light-table[data-gallery="strip"] .gallery {
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

.light-table:is([data-size="S"], [data-size="M"]) .toolbar .word {
    display: none;
}

.light-table:is([data-size="S"], [data-size="M"]) .segment button {
    padding-inline: 0.5rem;
}

@media (max-width: 48rem) {
    .light-table .toolbar .word {
        display: none;
    }

    .light-table[data-shown="grid2"] .panes {
        grid-template-columns: minmax(0, 1fr);
        grid-template-rows: repeat(2, minmax(0, 1fr));
    }
}
</style>
