<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from "vue";
import { useGettext } from "vue3-gettext";

import CenturyHistogram from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/CenturyHistogram.vue";
import RangeSlider from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/RangeSlider.vue";

import type {
    PeriodEvent,
    PeriodMatch,
    RangeFacet,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

type Bounds = [number, number];
type Side = "from" | "to";

export interface PeriodChange {
    period: Bounds | null;
    match: PeriodMatch;
    event: PeriodEvent;
    undated: boolean;
}

const FIELD_DELAY_MS = 300;
const YEAR_TEXT = /^-?\d{1,4}$/;
/** Whether an event other than production has dated rows to count. */
const MODIFICATION_HAS_DATA = false;

/**
 * The production-date facet: which event is dated (Modification is offered
 * but disabled while it has no data), a century histogram, a two-thumb slider,
 * « From » and « To » fields brought back to the bounds of the dated rows, the
 * rule (overlap or entirely within, chosen in `PeriodRuleMenu`, which the rail
 * lays on the title line; a note under the fields names the rule while it is
 * not the default one) and whether undated rows are kept. With no
 * period the slider rests on the bounds and the fields are empty. Every edit
 * emits the whole state in `change`; a typed year waits 300 ms (or a `change`
 * event) before it does, a drag only at its end.
 */
const props = defineProps<{
    facet: RangeFacet;
    period: Bounds | null;
    match: PeriodMatch;
    event: PeriodEvent;
    undated: boolean;
}>();
const emit = defineEmits<{ change: [payload: PeriodChange] }>();

const { $gettext, interpolate } = useGettext();
const baseId = useId();

const draft = ref<Bounds | null>(null);
const texts = ref<Record<Side, string>>({ from: "", to: "" });
const announcement = ref("");
let timer: ReturnType<typeof setTimeout> | null = null;

const bounds = computed<Bounds>(() => [props.facet.min, props.facet.max]);
const shown = computed<Bounds | null>(() => draft.value ?? props.period);
const sliderValue = computed<Bounds>(() => {
    const [low, high] = shown.value ?? bounds.value;
    return [clampYear(low), clampYear(high)];
});
const reasonId = computed(() => `${baseId}-reason`);

watch(
    shown,
    (period) => {
        texts.value = {
            from: period ? String(period[0]) : "",
            to: period ? String(period[1]) : "",
        };
    },
    { immediate: true },
);

onBeforeUnmount(cancelTimer);

function clampYear(year: number): number {
    return Math.min(Math.max(year, props.facet.min), props.facet.max);
}

function cancelTimer(): void {
    if (timer !== null) clearTimeout(timer);
    timer = null;
}

function send(change: Partial<PeriodChange>): void {
    emit("change", {
        period: props.period,
        match: props.match,
        event: props.event,
        undated: props.undated,
        ...change,
    });
}

/** Emits `period`, except a null one while none is held. */
function sendPeriod(period: Bounds | null): void {
    if (period === null && props.period === null) return;
    send({ period });
}

function chooseEvent(event: PeriodEvent): void {
    if (event === "modification" && !MODIFICATION_HAS_DATA) return;
    if (event !== props.event) send({ event });
}

function onSliderInput(value: Bounds): void {
    draft.value = value;
}

/** `value`, or null when it spans the whole bounds: no period then. */
function periodOf(value: Bounds): Bounds | null {
    const [min, max] = bounds.value;
    return value[0] <= min && value[1] >= max ? null : value;
}

function onSliderChange(value: Bounds): void {
    draft.value = null;
    sendPeriod(periodOf(value));
}

function onCentury(from: number, to: number): void {
    const next: Bounds = [
        Math.max(from, props.facet.min),
        Math.min(to, props.facet.max),
    ];
    const same = props.period?.[0] === next[0] && props.period?.[1] === next[1];
    sendPeriod(same ? null : periodOf(next));
}

function sideName(side: Side): string {
    return side === "from" ? $gettext("From") : $gettext("To");
}

function announce(side: Side, year: number): void {
    announcement.value = interpolate(
        $gettext("%{field} brought back to %{year}"),
        { field: sideName(side), year },
        true,
    );
}

/** Reads the fields: an empty one rests on its bound; a year outside the bounds, or past the other field, is brought back and announced. */
function commitFields(side: Side): void {
    cancelTimer();
    const raw = texts.value[side].trim();
    if (raw !== "" && !YEAR_TEXT.test(raw)) {
        resetTexts();
        return;
    }
    const current = props.period;
    const other: Side = side === "from" ? "to" : "from";
    const otherRaw = texts.value[other].trim();
    if (raw === "" && otherRaw === "") {
        if (current !== null) send({ period: null });
        return;
    }
    const [min, max] = bounds.value;
    let low = texts.value.from.trim() === "" ? min : Number(texts.value.from);
    let high = texts.value.to.trim() === "" ? max : Number(texts.value.to);
    if (!YEAR_TEXT.test(String(low)) || !YEAR_TEXT.test(String(high))) {
        resetTexts();
        return;
    }
    if (raw !== "") {
        let year = Number(raw);
        const lowest = side === "from" ? min : low;
        const highest = side === "to" ? max : high;
        if (year < lowest) year = lowest;
        if (year > highest) year = highest;
        if (year !== Number(raw)) announce(side, year);
        if (side === "from") low = year;
        else high = year;
    }
    low = Math.min(low, high);
    texts.value = { from: String(low), to: String(high) };
    const next = periodOf([low, high]);
    const unchanged = next
        ? current?.[0] === low && current?.[1] === high
        : current === null;
    if (!unchanged) send({ period: next });
}

function resetTexts(): void {
    texts.value = {
        from: props.period ? String(props.period[0]) : "",
        to: props.period ? String(props.period[1]) : "",
    };
}

function onType(side: Side, event: Event): void {
    texts.value = {
        ...texts.value,
        [side]: (event.target as HTMLInputElement).value,
    };
    cancelTimer();
    timer = setTimeout(() => commitFields(side), FIELD_DELAY_MS);
}

function resetMatch(): void {
    send({ match: "overlap" });
}

function toggleUndated(event: Event): void {
    send({ undated: (event.target as HTMLInputElement).checked });
}

function undatedLabel(): string {
    return interpolate(
        $gettext("Include undated (%{n})"),
        { n: props.facet.undated },
        true,
    );
}
</script>

<template>
    <div class="period-facet">
        <div
            class="event"
            role="radiogroup"
            :aria-label="$gettext('Dated event')"
        >
            <button
                type="button"
                class="choice"
                role="radio"
                :aria-checked="props.event === 'production' ? 'true' : 'false'"
                @click="chooseEvent('production')"
            >
                <span>{{ $gettext("Production") }}</span>
            </button>
            <button
                type="button"
                class="choice"
                role="radio"
                aria-disabled="true"
                :aria-checked="
                    props.event === 'modification' ? 'true' : 'false'
                "
                :aria-describedby="reasonId"
                @click="chooseEvent('modification')"
            >
                <span>{{ $gettext("Modification") }}</span>
            </button>
            <span
                :id="reasonId"
                class="visually-hidden"
                >{{ $gettext("No data for this event yet") }}</span
            >
        </div>
        <CenturyHistogram
            :buckets="props.facet.buckets"
            :min="props.facet.min"
            :max="props.facet.max"
            :selected="shown"
            @select="onCentury"
        />
        <RangeSlider
            :min="props.facet.min"
            :max="props.facet.max"
            :value="sliderValue"
            @input="onSliderInput"
            @change="onSliderChange"
        />
        <div class="fields">
            <label class="field">
                <span class="field-name">{{ $gettext("From") }}</span>
                <input
                    class="field-from"
                    type="number"
                    inputmode="numeric"
                    :value="texts.from"
                    :placeholder="String(props.facet.min)"
                    @input="onType('from', $event)"
                    @change="commitFields('from')"
                />
            </label>
            <span
                class="dash"
                aria-hidden="true"
                >–</span
            >
            <label class="field">
                <span class="field-name">{{ $gettext("To") }}</span>
                <input
                    class="field-to"
                    type="number"
                    inputmode="numeric"
                    :value="texts.to"
                    :placeholder="String(props.facet.max)"
                    @input="onType('to', $event)"
                    @change="commitFields('to')"
                />
            </label>
        </div>
        <p
            class="visually-hidden"
            role="status"
        >
            {{ announcement }}
        </p>
        <p
            v-if="props.match === 'within'"
            class="rule-note"
        >
            <span>{{ $gettext("Entirely within the period") }}</span>
            <button
                type="button"
                class="rule-reset"
                @click="resetMatch"
            >
                {{ $gettext("Reset") }}
            </button>
        </p>
        <label class="option">
            <input
                class="undated"
                type="checkbox"
                :checked="props.undated"
                @change="toggleUndated"
            />
            <span class="undated-label">{{ undatedLabel() }}</span>
        </label>
    </div>
</template>

<style scoped>
.period-facet {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.5rem;
}

.period-facet .event {
    display: flex;
    min-inline-size: 0;
    gap: 0.125rem;
    padding: 0.125rem;
    border-radius: 0.375rem;
    background: var(--bg-alt);
}

.period-facet .choice {
    flex: 1 1 0;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: none;
    border-radius: 0.25rem;
    background: transparent;
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
}

.period-facet .choice[aria-checked="true"] {
    background: var(--surface);
    color: var(--ink);
    font-weight: 600;
    box-shadow: var(--shadow-sm);
}

.period-facet .choice[aria-disabled="true"] {
    color: var(--ink-dim);
    cursor: not-allowed;
}

.period-facet .fields {
    display: flex;
    align-items: flex-end;
    gap: 0.5rem;
}

.period-facet .field {
    display: grid;
    flex: 1 1 0;
    gap: 0.125rem;
    min-inline-size: 0;
    font-size: 0.75rem;
    color: var(--ink-muted);
}

.period-facet .field input {
    box-sizing: border-box;
    inline-size: 100%;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font-family: var(--font-mono);
    font-size: 0.8125rem;
}

.period-facet .dash {
    padding-block-end: 0.75rem;
    color: var(--ink-muted);
}

.period-facet .rule-note {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem 0.5rem;
    margin: 0;
    font-size: 0.75rem;
    font-weight: 600;
}

.period-facet .rule-reset {
    min-block-size: var(--explorer-target, 2rem);
    padding: 0 0.25rem;
    border: none;
    background: none;
    color: var(--blue-text);
    font: inherit;
    font-weight: 400;
    text-decoration: underline;
    cursor: pointer;
}

.period-facet .option {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2.75rem);
    font-size: 0.8125rem;
    cursor: pointer;
}

.period-facet .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

.period-facet .choice:focus-visible,
.period-facet .rule-reset:focus-visible,
.period-facet input:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
