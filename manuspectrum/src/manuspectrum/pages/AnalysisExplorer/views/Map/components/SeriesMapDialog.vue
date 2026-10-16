<script setup lang="ts">
import {
    computed,
    nextTick,
    onBeforeUnmount,
    ref,
    useTemplateRef,
    watch,
} from "vue";
import { useGettext } from "vue3-gettext";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
import FocusSlotDot from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusSlotDot.vue";
import SeriesMap from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/SeriesMap.vue";

import type { Bounds } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import type {
    MapSnapshot,
    MiniMap,
    SnapshotSize,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/multiples.ts";

/** The drawing box when the dialog cannot be measured (no layout). */
const FALLBACK_SIZE: SnapshotSize = { width: 960, height: 600 };
const STEPS: Readonly<Record<string, number>> = {
    ArrowLeft: -1,
    ArrowRight: 1,
};

/**
 * One map of the series shown large in a modal `<dialog>` (`showModal`;
 * Escape closes it, the page does not scroll meanwhile). `index` is the
 * map's place in `maps`: set, the dialog opens, measures its drawing box
 * and emits `measure` with it, so the parent can take a snapshot at that
 * size; null, it closes. The map is drawn in that box by `SeriesMap`, on
 * `background`, with its caption, the key of its symbols, the previous and
 * next maps of the series (also on the arrow keys) and « Show on the map »
 * (`show`). While open, a change of `bounds` measures and emits `measure`
 * again, and a `maps` that no longer holds `index` closes it. Closing,
 * however it happens, emits `close`; the parent gives the focus back.
 */
const props = defineProps<{
    maps: MiniMap[];
    index: number | null;
    bounds: Bounds;
    background: MapSnapshot | null;
    title: string;
    counts: string;
    followedSlot: number | null;
}>();
const emit = defineEmits<{
    close: [];
    navigate: [index: number];
    measure: [size: SnapshotSize];
    show: [map: MiniMap];
}>();

const { $gettext, interpolate } = useGettext();

const dialog = useTemplateRef<HTMLDialogElement>("dialog");
const drawing = useTemplateRef<HTMLElement>("drawing");
const closeButton =
    useTemplateRef<InstanceType<typeof IconButton>>("close-button");
const size = ref<SnapshotSize | null>(null);
let pageOverflow: string | null = null;

const map = computed(() =>
    props.index === null ? null : props.maps[props.index] ?? null,
);
const boundsKey = computed(() =>
    [
        props.bounds.west,
        props.bounds.south,
        props.bounds.east,
        props.bounds.north,
    ].join(","),
);
const atFirst = computed(() => (props.index ?? 0) <= 0);
const atLast = computed(() => (props.index ?? 0) >= props.maps.length - 1);
const position = computed(() =>
    interpolate(
        $gettext("Map %{n} of %{total}"),
        { n: (props.index ?? 0) + 1, total: props.maps.length },
        true,
    ),
);

watch(
    () => props.index !== null,
    async (open) => {
        const element = dialog.value;
        if (!element) return;
        if (!open) {
            if (element.open) element.close();
            return;
        }
        if (element.open) return;
        element.showModal();
        lockPage();
        await nextTick();
        size.value = measure();
        emit("measure", size.value);
        closeButton.value?.element?.focus({ preventScroll: true });
    },
    { flush: "post" },
);

watch(map, (current) => {
    if (current === null && dialog.value?.open) close();
});
watch(
    boundsKey,
    () => {
        if (!dialog.value?.open) return;
        size.value = measure();
        emit("measure", size.value);
    },
    { flush: "post" },
);

onBeforeUnmount(() => {
    unlockPage();
    if (dialog.value?.open) dialog.value.close();
});

function measure(): SnapshotSize {
    const box = drawing.value?.getBoundingClientRect();
    if (!box || box.width <= 0 || box.height <= 0) return FALLBACK_SIZE;
    return { width: Math.round(box.width), height: Math.round(box.height) };
}

function lockPage(): void {
    if (pageOverflow !== null) return;
    pageOverflow = document.documentElement.style.overflow;
    document.documentElement.style.overflow = "hidden";
}

function unlockPage(): void {
    if (pageOverflow === null) return;
    document.documentElement.style.overflow = pageOverflow;
    pageOverflow = null;
}

function onClosed(): void {
    unlockPage();
    size.value = null;
    emit("close");
}

function close(): void {
    dialog.value?.close();
}

function go(step: number): void {
    if (props.index === null) return;
    const next = props.index + step;
    if (next < 0 || next > props.maps.length - 1) return;
    emit("navigate", next);
}

function onKeydown(event: KeyboardEvent): void {
    if (!(event.key in STEPS)) return;
    event.preventDefault();
    go(STEPS[event.key]);
}

function show(): void {
    if (map.value) emit("show", map.value);
}
</script>

<template>
    <dialog
        ref="dialog"
        class="series-map-dialog"
        :aria-label="props.title || undefined"
        @close="onClosed"
        @keydown="onKeydown"
    >
        <div
            v-if="map"
            class="body"
        >
            <header class="head">
                <h2 class="name">
                    <FocusSlotDot
                        v-if="props.followedSlot !== null"
                        size="small"
                        :number="props.followedSlot"
                    />
                    <span
                        class="title"
                        :lang="map.title?.lang || undefined"
                        >{{ props.title }}</span
                    >
                </h2>
                <span class="counts">{{ props.counts }}</span>
                <span class="position">{{ position }}</span>
                <span class="actions">
                    <IconButton
                        icon="chevron-left"
                        data-action="previous"
                        :label="$gettext('Previous map')"
                        :disabled="atFirst"
                        @click="go(-1)"
                    />
                    <IconButton
                        icon="chevron-right"
                        data-action="next"
                        :label="$gettext('Next map')"
                        :disabled="atLast"
                        @click="go(1)"
                    />
                    <IconButton
                        ref="close-button"
                        icon="times"
                        data-action="close"
                        :label="$gettext('Close')"
                        @click="close"
                    />
                </span>
            </header>
            <div
                ref="drawing"
                class="drawing"
            >
                <SeriesMap
                    v-if="size"
                    :map="map"
                    :bounds="props.bounds"
                    :background="props.background"
                    :width="size.width"
                    :height="size.height"
                    :followed-slot="props.followedSlot"
                />
            </div>
            <footer class="foot">
                <ul
                    class="key"
                    :aria-label="$gettext('Key')"
                >
                    <li>
                        <span
                            class="symbol attested"
                            aria-hidden="true"
                        ></span>
                        <span>{{ $gettext("attested") }}</span>
                    </li>
                    <li>
                        <span
                            class="symbol absent"
                            aria-hidden="true"
                        ></span>
                        <span>{{ $gettext("not attested here") }}</span>
                    </li>
                    <li>
                        <span
                            class="symbol pale"
                            aria-hidden="true"
                        ></span>
                        <span>{{ $gettext("lower reliability") }}</span>
                    </li>
                    <li>
                        <span
                            class="symbol dashed"
                            aria-hidden="true"
                        ></span>
                        <span>{{
                            $gettext("attributed place: region or parent place")
                        }}</span>
                    </li>
                </ul>
                <button
                    type="button"
                    class="show"
                    @click="show"
                >
                    <span>{{ $gettext("Show on the map") }}</span>
                </button>
            </footer>
        </div>
    </dialog>
</template>

<style scoped>
/* WindowGrid .enlarged-dialog */
.series-map-dialog {
    inline-size: min(92vw, 80rem);
    max-inline-size: none;
    block-size: min(88vh, 56rem);
    max-block-size: none;
    margin: auto;
    padding: 0;
    overflow: hidden;
    border: 0.0625rem solid var(--border-hover);
    border-radius: var(--explorer-radius, 0.625rem);
    background: var(--stage);
    box-shadow: var(--shadow-lg);
    color: var(--surface);
}

.series-map-dialog::backdrop {
    background: color-mix(in srgb, var(--ink) 45%, transparent);
}

.series-map-dialog .body {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto;
    gap: 0.5rem;
    block-size: 100%;
    padding: 0.75rem;
}

.series-map-dialog .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem 0.75rem;
}

.series-map-dialog .name {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    min-inline-size: 0;
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
}

.series-map-dialog .title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.series-map-dialog .counts,
.series-map-dialog .position {
    color: color-mix(in srgb, var(--surface) 75%, transparent);
    font-family: var(--font-mono);
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
}

.series-map-dialog .actions {
    display: flex;
    gap: 0.25rem;
    margin-inline-start: auto;
}

.series-map-dialog .actions :deep(.icon-button-control) {
    color: var(--surface);
}

.series-map-dialog .actions :deep(.icon-button-control:hover) {
    background: var(--stage-soft);
}

.series-map-dialog .actions :deep(.icon-button-control[aria-disabled="true"]) {
    opacity: 0.45;
}

.series-map-dialog .drawing {
    display: grid;
    min-block-size: 0;
    overflow: hidden;
    border-radius: 0.375rem;
    background: var(--map-land);
}

.series-map-dialog .drawing :deep(.series-map) {
    block-size: 100%;
}

.series-map-dialog .foot {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem 1rem;
}

.series-map-dialog .key {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem 1rem;
    margin: 0;
    padding: 0;
    list-style: none;
    font-size: 0.75rem;
}

.series-map-dialog .key li {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
}

.series-map-dialog .symbol {
    flex: none;
    inline-size: 0.75rem;
    block-size: 0.75rem;
    border: 0.0625rem solid var(--series-context);
    border-radius: 50%;
}

.series-map-dialog .symbol.attested {
    border-color: var(--surface);
    background: var(--surface);
}

.series-map-dialog .symbol.pale {
    border: 0.125rem solid var(--surface);
}

.series-map-dialog .symbol.dashed {
    border: 0.125rem dashed var(--series-context);
}

/* FolioMap .control */
.series-map-dialog .show {
    min-block-size: var(--explorer-target, 2rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid color-mix(in srgb, var(--surface) 30%, transparent);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.8125rem;
    font-weight: 600;
    cursor: pointer;
}

.series-map-dialog .show:focus-visible {
    outline: 0.125rem solid var(--surface);
    outline-offset: 0.125rem;
}

@media (forced-colors: active) {
    .series-map-dialog .symbol {
        border-color: CanvasText;
    }
}
</style>
