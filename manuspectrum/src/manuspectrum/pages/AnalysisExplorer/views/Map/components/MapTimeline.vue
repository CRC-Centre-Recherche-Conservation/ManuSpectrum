<script setup lang="ts">
import { computed, ref, useId, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import CollapsibleSection from "@/manuspectrum/pages/AnalysisExplorer/components/CollapsibleSection.vue";
import FocusSlotDot from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusSlotDot.vue";

import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";
import {
    foldText,
    ordinal,
    yearAndCentury,
} from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import {
    BIN_YEARS,
    aoristic,
    intervalOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/aoristic.ts";
import { formatEventDate } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/event-format.ts";
import { inBrush } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/place-symbols.ts";

import type {
    EventType,
    Label,
    MapEvent,
    NamedRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    DatedItem,
    HistogramBin,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/aoristic.ts";
import type { TrackedMaterial } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";

type Edge = "low" | "high";

type Column =
    | { kind: "bin"; bin: HistogramBin; start: number; width: number }
    | { kind: "fold"; from: number; to: number; start: number; width: number };

interface Part {
    key: string;
    y: number;
    height: number;
}

interface DocumentRow {
    id: string;
    name: NamedRef["name"];
    events: MapEvent[];
}

const TYPES: readonly EventType[] = [
    "production",
    "modification",
    "alteration",
];
const OTHER = "other";
const FOLD_UNITS = 0.6;
const GAP_SHARE = 0.12;
const PERCENT = 100;
const CENTURY = 100;
const MAX_LABELS = 6;
const ROWS_STEP = 100;
const EDGES: readonly Edge[] = ["low", "high"];
const ARROW_STEP = 1;
const PAGE_STEP = 25;
/** A release closer than this to its press, in CSS pixels, is a click: it sets no brush. */
const CLICK_SLOP_PX = 3;
const KEY_STEPS: Readonly<Record<string, number>> = {
    ArrowRight: ARROW_STEP,
    ArrowUp: ARROW_STEP,
    ArrowLeft: -ARROW_STEP,
    ArrowDown: -ARROW_STEP,
    PageUp: PAGE_STEP,
    PageDown: -PAGE_STEP,
};

/**
 * The timeline of the kept events (not brushed: the histogram is the
 * context of the brush). An aoristic histogram stacks, per bin, the parts
 * of each followed material, else of each event type; whole centuries without a dated event fold into one
 * hatched column. Each bin has a button that opens its period. The two
 * edges of the brush are its sliders (at the domain ends while nothing is
 * brushed): a captured pointer drags one along the histogram's own axis
 * and sends the brush once, on release, unless the edge did not move (a
 * press focuses the edge and sets nothing); arrows move it a year, Page keys
 * 25, Home and End to the bound, an edge never passing the other one. The
 * bins outside the brush fade. The
 * « Documents » rows list the documents of the brushed events with their
 * events laid on the same span, a followed material as its slot digit.
 */
const props = defineProps<{
    events: MapEvent[];
    tracked: TrackedMaterial[];
    brush: [number, number] | null;
    approximate: boolean;
}>();
const emit = defineEmits<{
    brush: [value: [number, number] | null];
    "update:approximate": [value: boolean];
    "open-period": [range: { from: number; to: number }];
    "open-document": [id: string];
}>();

const gettext = useGettext();
const { $gettext, $ngettext, interpolate } = gettext;
const { eventTypeLabel } = useVocabulary();
const hatchId = useId();

const rowsOpen = ref(false);
const rowLimit = ref(ROWS_STEP);
const hot = ref<number | null>(null);
const plot = useTemplateRef<HTMLElement>("plot");
const held = ref<Edge | null>(null);
const draft = ref<[number, number] | null>(null);
let pressX = 0;

const items = computed<DatedItem[]>(() =>
    props.events.flatMap((event) => {
        const interval = intervalOf(event.date);
        if (interval === null) return [];
        const carried = new Set(event.materials.map((m) => m.id));
        const keys =
            props.tracked.length > 0
                ? props.tracked
                      .filter(({ uri }) => carried.has(uri))
                      .map(({ slot }) => `slot:${slot}`)
                : [`type:${event.type}`];
        return [
            {
                interval,
                keys: keys.length > 0 ? keys : [OTHER],
            },
        ];
    }),
);
const histogram = computed(() => aoristic(items.value));
const keyOrder = computed<string[]>(() =>
    props.tracked.length > 0
        ? [
              ...[...props.tracked]
                  .sort((a, b) => a.slot - b.slot)
                  .map(({ slot }) => `slot:${slot}`),
              OTHER,
          ]
        : TYPES.map((type) => `type:${type}`),
);
const columns = computed<Column[]>(() => {
    const shape = histogram.value;
    if (shape === null) return [];
    const units = shape.segments.reduce(
        (sum, segment) =>
            sum + (segment.kind === "bins" ? segment.bins.length : FOLD_UNITS),
        0,
    );
    const unit = PERCENT / units;
    const out: Column[] = [];
    let start = 0;
    for (const segment of shape.segments) {
        if (segment.kind === "fold") {
            out.push({ ...segment, start, width: unit * FOLD_UNITS });
            start += unit * FOLD_UNITS;
            continue;
        }
        for (const bin of segment.bins) {
            out.push({ kind: "bin", bin, start, width: unit });
            start += unit;
        }
    }
    return out;
});
const bins = computed(() =>
    columns.value.flatMap((column) =>
        column.kind === "bin"
            ? [{ ...column, parts: partsOf(column.bin) }]
            : [],
    ),
);
const folds = computed(() =>
    columns.value.flatMap((column) => (column.kind === "fold" ? [column] : [])),
);
const edges = computed<[number, number]>(() => {
    const shape = histogram.value;
    if (shape === null) return [0, 0];
    const brush = props.brush ?? [shape.from, shape.to];
    return [
        Math.max(shape.from, Math.min(brush[0], shape.to)),
        Math.min(shape.to, Math.max(brush[1], shape.from)),
    ];
});
const shown = computed<[number, number] | null>(
    () => draft.value ?? props.brush,
);
const shownEdges = computed<[number, number]>(() => draft.value ?? edges.value);
const band = computed(() => {
    const brush = shown.value;
    if (brush === null || histogram.value === null) return null;
    const start = xOf(brush[0]);
    return { start, width: Math.max(0, xOf(brush[1] + 1) - start) };
});
const axisLabels = computed(() => {
    const starts = bins.value.filter(
        ({ bin }) => (bin.from - 1) % CENTURY === 0,
    );
    const every = Math.max(1, Math.ceil(starts.length / MAX_LABELS));
    return starts
        .filter((_, index) => index % every === 0)
        .map(({ bin, start }) => ({
            key: bin.from,
            start,
            text: ordinal(
                Math.floor((bin.from - 1) / CENTURY) + 1,
                gettext.current,
            ),
        }));
});
const binText = computed(() =>
    histogram.value?.binYears === BIN_YEARS
        ? $gettext(
              "An imprecise date is spread over the bins it covers (“14th c.” = ¼ + ¼ + ¼ + ¼)",
          )
        : $gettext(
              "An imprecise date is spread over the bins it covers (“14th c.” = ½ + ½)",
          ),
);
const stackText = computed(() =>
    props.tracked.length > 0
        ? $gettext("colours = followed materials")
        : $gettext("colours = event types"),
);
const keyEntries = computed(() => {
    const present = new Set(items.value.flatMap((item) => [...item.keys]));
    return keyOrder.value
        .filter((key) => present.has(key))
        .map((key) => ({ key, slot: slotOfKey(key), text: keyLabel(key) }));
});
const rows = computed<DocumentRow[]>(() => {
    const found = new Map<string, DocumentRow>();
    for (const event of props.events) {
        if (!inBrush(event, props.brush)) continue;
        let row = found.get(event.document.id);
        if (!row) {
            row = {
                id: event.document.id,
                name: event.document.name,
                events: [],
            };
            found.set(row.id, row);
        }
        row.events.push(event);
    }
    return [...found.values()].sort((a, b) =>
        foldText(a.name.value).localeCompare(foldText(b.name.value)),
    );
});
const shownRows = computed(() => rows.value.slice(0, rowLimit.value));
const rowsTitle = computed(() =>
    interpolate(
        props.brush
            ? $gettext("Documents of the period (%{n})")
            : $gettext("Documents (%{n})"),
        { n: rows.value.length },
        true,
    ),
);
const rowsSummary = computed(() => {
    const present = new Set(
        rows.value.flatMap((row) => row.events.map((event) => event.type)),
    );
    return TYPES.filter((type) => present.has(type))
        .map((type) => eventTypeLabel(type))
        .join(", ");
});

function partsOf(bin: HistogramBin): Part[] {
    const max = histogram.value?.max || 1;
    const parts: Part[] = [];
    let top = PERCENT;
    for (const key of keyOrder.value) {
        const value = bin.parts[key] ?? 0;
        if (value <= 0) continue;
        const height = (value / max) * PERCENT;
        top -= height;
        parts.push({ key, y: top, height });
    }
    return parts;
}

function xOf(year: number): number {
    for (const column of columns.value) {
        const from = column.kind === "bin" ? column.bin.from : column.from;
        const to = column.kind === "bin" ? column.bin.to : column.to;
        if (year > to) continue;
        const share = Math.max(0, year - from) / (to - from + 1);
        return column.start + column.width * share;
    }
    return PERCENT;
}

/** The year at a share of the plot, the inverse of `xOf` (fractional). */
function yearOf(share: number): number {
    const all = columns.value;
    for (const [index, column] of all.entries()) {
        if (share > column.start + column.width && index < all.length - 1) {
            continue;
        }
        const from = column.kind === "bin" ? column.bin.from : column.from;
        const to = column.kind === "bin" ? column.bin.to : column.to;
        const within =
            column.width > 0 ? (share - column.start) / column.width : 0;
        return from + Math.min(1, Math.max(0, within)) * (to - from + 1);
    }
    return 0;
}

function edgeAt(edge: Edge): number {
    return edge === "low"
        ? xOf(shownEdges.value[0])
        : xOf(shownEdges.value[1] + 1);
}

function withEdge(edge: Edge, year: number): [number, number] {
    const shape = histogram.value;
    const [low, high] = edges.value;
    if (shape === null) return [low, high];
    return edge === "low"
        ? [Math.min(Math.max(year, shape.from), high), high]
        : [low, Math.max(Math.min(year, shape.to), low)];
}

function edgeYearAt(edge: Edge, clientX: number): number | null {
    const rect = plot.value?.getBoundingClientRect();
    if (!rect || rect.width <= 0) return null;
    const share = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    const year = Math.round(yearOf(share * PERCENT));
    return edge === "low" ? year : year - 1;
}

function boundsOf(edge: Edge): [number, number] {
    const shape = histogram.value;
    const [low, high] = shownEdges.value;
    if (shape === null) return [low, high];
    return edge === "low" ? [shape.from, high] : [low, shape.to];
}

function valueOf(edge: Edge): number {
    return edge === "low" ? shownEdges.value[0] : shownEdges.value[1];
}

function edgeLabel(edge: Edge): string {
    return edge === "low" ? $gettext("Earliest year") : $gettext("Latest year");
}

function edgeText(year: number): string {
    return yearAndCentury(year, $gettext, interpolate, gettext.current);
}

function onEdgeKeydown(edge: Edge, event: KeyboardEvent): void {
    const shape = histogram.value;
    if (shape === null || held.value !== null) return;
    const current = valueOf(edge);
    let target: number;
    if (event.key === "Home") {
        target = shape.from;
    } else if (event.key === "End") {
        target = shape.to;
    } else if (event.key in KEY_STEPS) {
        target = current + KEY_STEPS[event.key];
    } else {
        return;
    }
    event.preventDefault();
    emit("brush", withEdge(edge, target));
}

function onEdgePointerdown(edge: Edge, event: PointerEvent): void {
    if (event.button > 0) return;
    event.preventDefault();
    held.value = edge;
    draft.value = edges.value;
    pressX = event.clientX;
    const target = event.currentTarget as HTMLElement | null;
    target?.focus({ preventScroll: true });
    target?.setPointerCapture?.(event.pointerId);
}

function onEdgePointermove(edge: Edge, event: PointerEvent): void {
    if (held.value !== edge) return;
    const year = edgeYearAt(edge, event.clientX);
    if (year !== null) draft.value = withEdge(edge, year);
}

function onEdgePointerup(edge: Edge, event: PointerEvent): void {
    if (held.value !== edge) return;
    const year = edgeYearAt(edge, event.clientX);
    const next = year === null ? draft.value : withEdge(edge, year);
    const pressed = edges.value;
    const clicked = Math.abs(event.clientX - pressX) < CLICK_SLOP_PX;
    releaseEdge();
    if (next === null || clicked) return;
    if (next[0] === pressed[0] && next[1] === pressed[1]) return;
    emit("brush", next);
}

function releaseEdge(): void {
    held.value = null;
    draft.value = null;
}

function isOut(bin: HistogramBin): boolean {
    const brush = shown.value;
    return brush !== null && (bin.to < brush[0] || bin.from > brush[1]);
}

function slotOfKey(key: string): number | null {
    return key.startsWith("slot:") ? Number(key.slice(5)) : null;
}

function materialLabel(uri: string): Label {
    for (const event of props.events) {
        const found = event.materials.find((m) => m.id === uri);
        if (found) return found.name;
    }
    return { value: uri, lang: "" };
}

function keyLabel(key: string): string {
    if (key === OTHER) return $gettext("no followed material");
    const slot = slotOfKey(key);
    if (slot !== null) {
        const uri = props.tracked.find((entry) => entry.slot === slot)?.uri;
        return uri ? materialLabel(uri).value : "";
    }
    return eventTypeLabel(key.slice(5) as EventType);
}

function binName(bin: HistogramBin): string {
    const total = Math.round(bin.total * 10) / 10;
    return interpolate(
        $ngettext(
            "%{from}–%{to}: %{n} event",
            "%{from}–%{to}: %{n} events",
            total,
        ),
        {
            from: bin.from,
            to: bin.to,
            n: new Intl.NumberFormat(gettext.current, {
                maximumFractionDigits: 1,
            }).format(total),
        },
        true,
    );
}

function foldLabel(column: { from: number; to: number }): string {
    return interpolate(
        $gettext("%{start}–%{end}"),
        { start: column.from, end: column.to },
        true,
    );
}

function laneStyle(event: MapEvent): Record<string, string> | null {
    const interval = intervalOf(event.date);
    const shape = histogram.value;
    if (interval === null || shape === null) return null;
    const span = shape.to - shape.from + 1;
    const start = ((interval[0] - shape.from) / span) * PERCENT;
    const width = ((interval[1] - interval[0] + 1) / span) * PERCENT;
    return {
        "inset-inline-start": `${round(start)}%`,
        "inline-size": `${round(width)}%`,
    };
}

function round(value: number): number {
    return Math.round(value * PERCENT) / PERCENT;
}

function slotsOf(event: MapEvent): number[] {
    const carried = new Set(event.materials.map((m) => m.id));
    return props.tracked
        .filter(({ uri }) => carried.has(uri))
        .map(({ slot }) => slot)
        .sort((a, b) => a - b);
}

function rowDates(row: DocumentRow): string {
    const intervals = row.events.flatMap((event) => {
        const interval = intervalOf(event.date);
        return interval ? [interval] : [];
    });
    if (intervals.length === 0) return $gettext("undated");
    return formatEventDate(
        {
            start: Math.min(...intervals.map((interval) => interval[0])),
            end: Math.max(...intervals.map((interval) => interval[1])),
            approximate: row.events.some((event) => event.date.approximate),
        },
        $gettext,
        interpolate,
    );
}

function eventTitle(event: MapEvent): string {
    return interpolate(
        $gettext("%{type} · %{date}"),
        {
            type: eventTypeLabel(event.type),
            date: formatEventDate(event.date, $gettext, interpolate),
        },
        true,
    );
}

function showMore(): void {
    rowLimit.value += ROWS_STEP;
}
</script>

<template>
    <div class="map-timeline">
        <header class="head">
            <h3 class="kicker">{{ $gettext("Timeline") }}</h3>
            <p
                v-if="histogram"
                class="explain"
            >
                <span>{{ binText }}</span>
                <span aria-hidden="true">{{ " · " }}</span>
                <span>{{ stackText }}</span>
            </p>
            <label class="approximate">
                <input
                    type="checkbox"
                    :checked="props.approximate"
                    @change="
                        emit(
                            'update:approximate',
                            ($event.target as HTMLInputElement).checked,
                        )
                    "
                />
                <span>{{ $gettext("Include approximate dates (“c.”)") }}</span>
            </label>
            <button
                v-if="props.brush"
                type="button"
                class="clear"
                :aria-label="$gettext('Show the whole period')"
                @click="emit('brush', null)"
            >
                <span>{{ $gettext("Whole period") }}</span>
            </button>
        </header>

        <p
            v-if="!histogram"
            class="empty"
        >
            <span>{{ $gettext("No dated event among the kept events.") }}</span>
        </p>
        <template v-else>
            <div
                ref="plot"
                class="plot"
            >
                <svg
                    class="bars"
                    role="img"
                    :aria-label="$gettext('Events through time')"
                >
                    <defs>
                        <pattern
                            :id="hatchId"
                            width="4"
                            height="4"
                            patternUnits="userSpaceOnUse"
                            patternTransform="rotate(45)"
                        >
                            <line
                                class="hatch-line"
                                x1="0"
                                y1="0"
                                x2="0"
                                y2="4"
                            />
                        </pattern>
                    </defs>
                    <g
                        v-for="(column, index) in bins"
                        :key="column.bin.from"
                        class="column"
                        :class="{
                            out: isOut(column.bin),
                            hot: hot === index,
                        }"
                    >
                        <rect
                            v-for="part in column.parts"
                            :key="part.key"
                            class="part"
                            :class="part.key.replace(':', '-')"
                            :x="`${round(column.start + column.width * GAP_SHARE)}%`"
                            :width="`${round(column.width * (1 - 2 * GAP_SHARE))}%`"
                            :y="`${round(part.y)}%`"
                            :height="`${round(part.height)}%`"
                        />
                        <rect
                            v-if="hot === index"
                            class="base"
                            :x="`${round(column.start + column.width * GAP_SHARE)}%`"
                            :width="`${round(column.width * (1 - 2 * GAP_SHARE))}%`"
                            y="97%"
                            height="3%"
                        />
                    </g>
                    <g
                        v-for="fold in folds"
                        :key="fold.from"
                        class="fold"
                    >
                        <title>{{ $gettext("No dated event") }}</title>
                        <rect
                            :x="`${round(fold.start + fold.width * GAP_SHARE)}%`"
                            :width="`${round(fold.width * (1 - 2 * GAP_SHARE))}%`"
                            y="0"
                            height="100%"
                            :fill="`url(#${hatchId})`"
                        />
                        <text
                            class="fold-label"
                            :x="`${round(fold.start + fold.width / 2)}%`"
                            y="50%"
                        >
                            {{ foldLabel(fold) }}
                        </text>
                    </g>
                </svg>
                <div
                    v-if="band"
                    class="band"
                    aria-hidden="true"
                    :style="{
                        'inset-inline-start': `${round(band.start)}%`,
                        'inline-size': `${round(band.width)}%`,
                    }"
                ></div>
                <div class="hits">
                    <button
                        v-for="(column, index) in bins"
                        :key="column.bin.from"
                        type="button"
                        class="bin"
                        :aria-label="binName(column.bin)"
                        :style="{
                            'inset-inline-start': `${round(column.start)}%`,
                            'inline-size': `${round(column.width)}%`,
                        }"
                        @mouseenter="hot = index"
                        @mouseleave="hot = null"
                        @focus="hot = index"
                        @blur="hot = null"
                        @click="
                            emit('open-period', {
                                from: column.bin.from,
                                to: column.bin.to,
                            })
                        "
                    ></button>
                </div>
                <div
                    v-for="edge in EDGES"
                    :key="edge"
                    class="edge"
                    :class="{
                        free: shown === null,
                        held: held === edge,
                    }"
                    role="slider"
                    tabindex="0"
                    :aria-label="edgeLabel(edge)"
                    :aria-valuemin="boundsOf(edge)[0]"
                    :aria-valuemax="boundsOf(edge)[1]"
                    :aria-valuenow="valueOf(edge)"
                    :aria-valuetext="edgeText(valueOf(edge))"
                    :style="{
                        'inset-inline-start': `${round(edgeAt(edge))}%`,
                    }"
                    @keydown="onEdgeKeydown(edge, $event)"
                    @pointerdown="onEdgePointerdown(edge, $event)"
                    @pointermove="onEdgePointermove(edge, $event)"
                    @pointerup="onEdgePointerup(edge, $event)"
                    @pointercancel="releaseEdge"
                    @lostpointercapture="releaseEdge"
                >
                    <span class="grip"></span>
                </div>
            </div>
            <div
                class="axis"
                aria-hidden="true"
            >
                <span
                    v-for="axisLabel in axisLabels"
                    :key="axisLabel.key"
                    :style="{
                        'inset-inline-start': `${round(axisLabel.start)}%`,
                    }"
                    >{{ axisLabel.text }}</span
                >
            </div>
            <ul
                class="key"
                :aria-label="$gettext('Key')"
            >
                <li
                    v-for="entry in keyEntries"
                    :key="entry.key"
                >
                    <FocusSlotDot
                        v-if="entry.slot !== null"
                        size="small"
                        :number="entry.slot"
                    />
                    <span
                        v-else
                        class="square"
                        :class="entry.key.replace(':', '-')"
                        aria-hidden="true"
                    ></span>
                    <span>{{ entry.text }}</span>
                </li>
            </ul>
        </template>

        <CollapsibleSection
            class="documents"
            :title="rowsTitle"
            :open="rowsOpen"
            :summary="rowsSummary"
            @toggle="rowsOpen = $event"
        >
            <ul class="rows">
                <li
                    v-for="row in shownRows"
                    :key="row.id"
                    class="document-row"
                >
                    <button
                        type="button"
                        class="open"
                        @click="emit('open-document', row.id)"
                    >
                        <span
                            class="name"
                            :lang="row.name.lang || undefined"
                            :title="row.name.value"
                            >{{ row.name.value }}</span
                        >
                        <span class="dates">{{ rowDates(row) }}</span>
                    </button>
                    <span
                        class="lane"
                        aria-hidden="true"
                    >
                        <template
                            v-for="event in row.events"
                            :key="event.id"
                        >
                            <span
                                v-if="laneStyle(event)"
                                :class="['bar', `type-${event.type}`]"
                                :style="laneStyle(event) ?? undefined"
                                :title="eventTitle(event)"
                            >
                                <span
                                    v-if="slotsOf(event).length > 0"
                                    class="pips"
                                >
                                    <FocusSlotDot
                                        v-for="slot in slotsOf(event)"
                                        :key="slot"
                                        size="small"
                                        :number="slot"
                                    />
                                </span>
                            </span>
                        </template>
                    </span>
                </li>
            </ul>
            <button
                v-if="rows.length > shownRows.length"
                type="button"
                class="more"
                @click="showMore"
            >
                <span>{{ $gettext("Show 100 more") }}</span>
            </button>
        </CollapsibleSection>
    </div>
</template>

<style scoped>
.map-timeline {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.75rem;
}

.map-timeline .head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.25rem 0.75rem;
}

/* OnThisPage h3 kicker */
.map-timeline .kicker {
    margin: 0;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-weight: 400;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.map-timeline .explain {
    flex: 1 1 16rem;
    color: var(--ink-muted);
    font-size: 0.75rem;
}

.map-timeline .approximate {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-block-size: var(--explorer-target, 2.75rem);
    color: var(--ink-muted);
    font-size: 0.75rem;
    cursor: pointer;
}

.map-timeline .approximate input {
    margin: 0;
    accent-color: var(--blue-text);
}

.map-timeline .approximate input:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

/* CorpusDocument .rail-foot .clear */
.map-timeline .clear {
    min-block-size: var(--explorer-target, 2.75rem);
    margin-inline-start: auto;
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
}

.map-timeline .empty {
    color: var(--ink-muted);
}

.map-timeline .plot {
    position: relative;
    block-size: 7.5rem;
    border-block-end: 0.0625rem solid var(--border-hover);
}

.map-timeline .bars {
    display: block;
    inline-size: 100%;
    block-size: 100%;
    overflow: visible;
}

.map-timeline .column {
    transition: opacity var(--dur-fast);
}

.map-timeline .column.out {
    opacity: var(--linked-fade);
}

.map-timeline .part {
    fill: var(--ink-dim);
}

.map-timeline .base {
    fill: var(--blue-text);
}

.map-timeline .slot-1 {
    fill: var(--focus-1);
    background: var(--focus-1);
}

.map-timeline .slot-2 {
    fill: var(--focus-2);
    background: var(--focus-2);
}

.map-timeline .slot-3 {
    fill: var(--focus-3);
    background: var(--focus-3);
}

.map-timeline .slot-4 {
    fill: var(--focus-4);
    background: var(--focus-4);
}

.map-timeline .type-production {
    fill: var(--series-1);
    background: var(--series-1);
}

.map-timeline .type-modification {
    fill: var(--series-2);
    background: var(--series-2);
}

.map-timeline .type-alteration {
    fill: var(--series-3);
    background: var(--series-3);
}

.map-timeline .other {
    fill: var(--series-context);
    background: var(--series-context);
}

.map-timeline .hatch-line {
    stroke: var(--ink-dim);
    stroke-width: 1;
    opacity: 0.5;
}

.map-timeline .fold-label {
    fill: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.5625rem;
    text-anchor: middle;
    dominant-baseline: middle;
    writing-mode: vertical-rl;
}

/* The brush: RangeSlider blue, its edges drawn by the handles */
.map-timeline .band {
    position: absolute;
    inset-block: 0;
    border-radius: 0.25rem;
    background: color-mix(in srgb, var(--blue-text) 6%, transparent);
    pointer-events: none;
}

.map-timeline .hits {
    position: absolute;
    inset: 0;
}

.map-timeline .bin {
    position: absolute;
    inset-block: 0;
    padding: 0;
    border: 0;
    background: transparent;
    cursor: pointer;
}

.map-timeline .edge {
    position: absolute;
    inset-block: 0;
    display: grid;
    place-items: center;
    inline-size: 1.5rem;
    transform: translateX(-50%);
    cursor: ew-resize;
    touch-action: none;
    user-select: none;
}

.map-timeline .edge::before {
    position: absolute;
    inset-block: 0;
    inset-inline-start: 50%;
    inline-size: 0.125rem;
    transform: translateX(-50%);
    background: var(--blue-text);
    content: "";
}

.map-timeline .edge.free::before {
    background: var(--border-hover);
}

.map-timeline .edge .grip {
    position: relative;
    box-sizing: border-box;
    inline-size: 0.625rem;
    block-size: 1.5rem;
    border: 0.125rem solid var(--blue-text);
    border-radius: 999rem;
    background: var(--surface);
    transition: background var(--dur-fast);
}

.map-timeline .edge:hover .grip,
.map-timeline .edge.held .grip {
    background: var(--blue-text);
}

.map-timeline .edge:focus-visible {
    outline: none;
}

.map-timeline .edge:focus-visible .grip {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.map-timeline .axis {
    position: relative;
    block-size: 1.25rem;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.625rem;
}

.map-timeline .axis span {
    position: absolute;
    inset-block-start: 0;
    white-space: nowrap;
}

.map-timeline .key {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem 0.75rem;
    margin: 0;
    padding: 0;
    color: var(--ink-muted);
    font-size: 0.6875rem;
    list-style: none;
}

.map-timeline .key li {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
}

.map-timeline .square {
    flex: none;
    inline-size: 0.625rem;
    block-size: 0.625rem;
    border-radius: 0.125rem;
}

.map-timeline .rows {
    display: grid;
    gap: 0.25rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.map-timeline .document-row {
    display: grid;
    grid-template-columns: minmax(10rem, 16rem) minmax(0, 1fr);
    align-items: center;
    gap: 0.5rem;
}

/* OnThisPage row button */
.map-timeline .open {
    display: flex;
    align-items: baseline;
    gap: 0.375rem;
    min-inline-size: 0;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: none;
    border-radius: 0.25rem;
    background: none;
    color: var(--ink);
    font: inherit;
    font-size: 0.75rem;
    text-align: start;
    cursor: pointer;
}

.map-timeline .open:hover {
    background: var(--bg-alt);
}

.map-timeline .open .name {
    min-inline-size: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.map-timeline .open .dates {
    flex: none;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
}

.map-timeline .lane {
    position: relative;
    display: block;
    block-size: 1.25rem;
    border-radius: 0.25rem;
    background: repeating-linear-gradient(
            90deg,
            var(--border) 0 0.0625rem,
            transparent 0.0625rem 25%
        ),
        var(--bg);
}

.map-timeline .bar {
    position: absolute;
    inset-block-start: 50%;
    block-size: 0.5rem;
    transform: translateY(-50%);
    min-inline-size: 0.5rem;
    border-radius: 999rem;
}

.map-timeline .pips {
    position: absolute;
    inset-block-start: 50%;
    inset-inline-start: 100%;
    display: inline-flex;
    gap: 0.0625rem;
    transform: translateY(-50%);
}

.map-timeline .more {
    justify-self: start;
    min-block-size: var(--explorer-target, 2.75rem);
    padding: 0;
    border: none;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
}

.map-timeline .more:hover {
    text-decoration: underline;
}

.map-timeline button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

@media (max-width: 48rem) {
    .map-timeline .document-row {
        grid-template-columns: minmax(0, 1fr);
    }
}

@media (prefers-reduced-motion: reduce) {
    .map-timeline .column,
    .map-timeline .edge .grip {
        transition: none;
    }
}
</style>
