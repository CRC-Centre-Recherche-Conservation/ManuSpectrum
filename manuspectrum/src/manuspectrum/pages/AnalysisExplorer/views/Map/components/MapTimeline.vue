<script setup lang="ts">
import { computed, ref, useId } from "vue";
import { useGettext } from "vue3-gettext";

import CollapsibleSection from "@/manuspectrum/pages/AnalysisExplorer/components/CollapsibleSection.vue";
import FocusSlotDot from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusSlotDot.vue";
import RangeSlider from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/RangeSlider.vue";

import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";
import {
    foldText,
    ordinal,
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

type Column =
    | { kind: "bin"; bin: HistogramBin; start: number; width: number }
    | { kind: "fold"; from: number; to: number; start: number; width: number };

interface Part {
    key: string;
    approx: boolean;
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
    "analysis",
    "sampling",
];
const SPAN_TYPES: ReadonlySet<EventType> = new Set([
    "production",
    "modification",
    "alteration",
]);
const OTHER = "other";
const FOLD_UNITS = 0.6;
const GAP_SHARE = 0.12;
const PERCENT = 100;
const CENTURY = 100;
const MAX_LABELS = 6;
const ROWS_STEP = 100;

/**
 * The timeline of the kept events (not brushed: the histogram is the
 * context of the brush). An aoristic histogram stacks, per bin, the parts
 * of each followed material, else of each event type, the approximate
 * share lighter; whole centuries without a dated event fold into one
 * hatched column. Each bin has a button that opens its period; the
 * slider under the axis sets the brush, the bins outside it fade. The
 * « Documents » rows list the documents of the brushed events with their
 * events laid on the same span, a followed material as its slot digit.
 */
const props = defineProps<{
    events: MapEvent[];
    tracked: TrackedMaterial[];
    brush: [number, number] | null;
}>();
const emit = defineEmits<{
    brush: [value: [number, number] | null];
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
                approximate: event.date.approximate,
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
const band = computed(() => {
    const brush = props.brush;
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
const sliderValue = computed<[number, number]>(() => {
    const shape = histogram.value;
    if (shape === null) return [0, 0];
    const brush = props.brush ?? [shape.from, shape.to];
    return [
        Math.max(shape.from, Math.min(brush[0], shape.to)),
        Math.min(shape.to, Math.max(brush[1], shape.from)),
    ];
});
const binText = computed(() =>
    histogram.value?.binYears === BIN_YEARS
        ? $gettext(
              "A date “14th c.” counts a quarter in each of its 25-year bins",
          )
        : $gettext(
              "A date “14th c.” counts a half in each of its 50-year bins",
          ),
);
const stackText = computed(() =>
    props.tracked.length > 0
        ? $gettext("stacked by followed material")
        : $gettext("stacked by event type"),
);
const keyEntries = computed(() => {
    const present = new Set(items.value.flatMap((item) => [...item.keys]));
    return keyOrder.value
        .filter((key) => present.has(key))
        .map((key) => ({ key, slot: slotOfKey(key), text: keyLabel(key) }));
});
const hasApprox = computed(() => items.value.some((item) => item.approximate));
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
        for (const approx of [false, true]) {
            const value = (approx ? bin.approx : bin.firm)[key] ?? 0;
            if (value <= 0) continue;
            const height = (value / max) * PERCENT;
            top -= height;
            parts.push({ key, approx, y: top, height });
        }
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

function partClass(part: Part): Record<string, boolean> {
    return {
        [part.key.replace(":", "-")]: true,
        approx: part.approx,
    };
}

function isOut(bin: HistogramBin): boolean {
    const brush = props.brush;
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
    if (!SPAN_TYPES.has(event.type)) {
        return { "inset-inline-start": `${round(start + width / 2)}%` };
    }
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
            <button
                v-if="props.brush"
                type="button"
                class="clear"
                @click="emit('brush', null)"
            >
                <span>{{ $gettext("Clear the period") }}</span>
            </button>
        </header>

        <p
            v-if="!histogram"
            class="empty"
        >
            <span>{{ $gettext("No dated event among the kept events.") }}</span>
        </p>
        <template v-else>
            <div class="plot">
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
                            :key="`${part.key}:${part.approx}`"
                            class="part"
                            :class="partClass(part)"
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
            <RangeSlider
                :min="histogram.from"
                :max="histogram.to"
                :value="sliderValue"
                @change="emit('brush', $event)"
            />
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
                <li v-if="hasApprox">
                    <span
                        class="square approx-sample"
                        aria-hidden="true"
                    ></span>
                    <span>{{ $gettext("lighter = approximate date") }}</span>
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
                                :class="[
                                    SPAN_TYPES.has(event.type)
                                        ? 'bar'
                                        : 'point',
                                    `type-${event.type}`,
                                    { approx: event.date.approximate },
                                ]"
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

.map-timeline .part.approx {
    opacity: 0.45;
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

.map-timeline .type-analysis {
    fill: var(--series-4);
    background: var(--series-4);
}

.map-timeline .type-sampling {
    fill: var(--series-5);
    background: var(--series-5);
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

/* The brush: RangeSlider blue */
.map-timeline .band {
    position: absolute;
    inset-block: 0;
    box-sizing: border-box;
    border-inline: 0.125rem solid var(--blue-text);
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

.map-timeline .square.approx-sample {
    background: var(--ink-dim);
    opacity: 0.45;
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

.map-timeline .bar,
.map-timeline .point {
    position: absolute;
    inset-block-start: 50%;
    block-size: 0.5rem;
    transform: translateY(-50%);
}

.map-timeline .bar {
    min-inline-size: 0.5rem;
    border-radius: 999rem;
}

.map-timeline .bar.approx {
    mask-image: linear-gradient(
        90deg,
        transparent,
        black 0.5rem,
        black calc(100% - 0.5rem),
        transparent
    );
}

.map-timeline .point {
    inline-size: 0.5rem;
    border-radius: 50%;
    translate: -50% 0;
    background: var(--ink);
    box-shadow: 0 0 0 0.0625rem var(--surface);
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
    .map-timeline .column {
        transition: none;
    }
}
</style>
