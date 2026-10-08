<script setup lang="ts">
import { computed, ref, useId } from "vue";
import { useGettext } from "vue3-gettext";

import FocusSlotDot from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusSlotDot.vue";

import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { declaredText } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/declared.ts";
import {
    PERIODIC_TABLE,
    atomicNumber,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/periodic.ts";

import type {
    StripDeclaredSlot,
    StripElement,
    StripLineRef,
    StripOverlap,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useXrfLens.ts";

const MAX_SUGGESTIONS = 8;
/** The rows above Na's (H to Ne) are left out of the grid. */
const SKIPPED_ROWS = 2;
const ENERGY_DIGITS = 2;

/**
 * The text equivalent of what the XRF lens draws, under the chart: one line
 * per pinned, previewed or lens element (its lines and energies, what the
 * Selection's materials declare of it), what each analysis declares, the
 * overlaps between drawn lines and the line that tells them apart. It also
 * holds the lens element picker: an « Add an element » combobox over the
 * line table's symbols and a mini periodic table (Na to U) of toggles. Lens
 * elements are the reader's own list; they never enter the focus.
 */
const props = defineProps<{
    elements: readonly StripElement[];
    declaredSlots: readonly StripDeclaredSlot[];
    overlaps: readonly StripOverlap[];
    /** Every symbol of the line table, by atomic number; empty while it loads. */
    symbols: readonly string[];
    /** The reader's lens elements. */
    lensSymbols: readonly string[];
    lang: string;
}>();

const emit = defineEmits<{
    (event: "toggle-element", payload: { symbol: string }): void;
    (event: "add-element", payload: { symbol: string }): void;
    (event: "remove-element", payload: { symbol: string }): void;
}>();

const { $gettext, interpolate } = useGettext();

const inputId = useId();
const listId = useId();
const query = ref("");
const suggestionsOpen = ref(false);
const activeIndex = ref(0);
const tableOpen = ref(false);
const unknownSymbol = ref<string | null>(null);

const numbers = computed(
    () =>
        new Intl.NumberFormat(props.lang, {
            minimumFractionDigits: ENERGY_DIGITS,
            maximumFractionDigits: ENERGY_DIGITS,
        }),
);
const known = computed(() => new Set(props.symbols));
const suggestions = computed(() => {
    const typed = query.value.trim().toLowerCase();
    return props.symbols
        .filter(
            (symbol) =>
                !props.lensSymbols.includes(symbol) &&
                (typed === "" || symbol.toLowerCase().startsWith(typed)),
        )
        .slice(0, MAX_SUGGESTIONS);
});
const showSuggestions = computed(
    () => suggestionsOpen.value && suggestions.value.length > 0,
);
const grid = computed(() =>
    PERIODIC_TABLE.filter((place) => known.value.has(place.symbol)).map(
        (place) => ({
            symbol: place.symbol,
            pressed: props.lensSymbols.includes(place.symbol),
            position: {
                gridRow: place.row - SKIPPED_ROWS,
                gridColumn: place.column,
            },
        }),
    ),
);
const hasContent = computed(
    () =>
        props.elements.length > 0 ||
        props.declaredSlots.length > 0 ||
        props.overlaps.length > 0,
);

function energy(value: number): string {
    return numbers.value.format(value);
}

function lineText(line: StripLineRef): string {
    return `${line.symbol} ${line.label} ${energy(line.energy)}`;
}

function linesText(element: StripElement): string {
    return element.lines
        .map((line) => `${line.label} ${energy(line.energy)}`)
        .join(" · ");
}

function declaredOf(element: StripElement): string {
    return element.declared
        ? declaredText(element.declared, { $gettext, interpolate })
        : "";
}

function missingText(symbol: string): string {
    return interpolate(
        $gettext("No line in the table for %{element} (Z 11–92)"),
        { element: symbol },
        true,
    );
}

function overlapText(overlap: StripOverlap): string {
    const values = { a: lineText(overlap.a), b: lineText(overlap.b) };
    if (!overlap.apartA || !overlap.apartB) {
        return interpolate($gettext("%{a} overlaps %{b}"), values, true);
    }
    return interpolate(
        $gettext("%{a} overlaps %{b}: tell apart with %{c} vs %{d}"),
        {
            ...values,
            c: lineText(overlap.apartA),
            d: lineText(overlap.apartB),
        },
        true,
    );
}

function declaredSlotText(entry: StripDeclaredSlot): string {
    const items = entry.items
        .map((item) =>
            item.level ? `${item.symbol} ${item.level.value}` : item.symbol,
        )
        .join(" · ");
    return `${interpolate(
        $gettext("Declared on %{slot}"),
        { slot: slotLabel(entry.slot) },
        true,
    )}: ${items}`;
}

function removeLabel(symbol: string): string {
    return interpolate(
        $gettext("Remove %{element}"),
        { element: symbol },
        true,
    );
}

function cellLabel(symbol: string): string {
    return interpolate(
        $gettext("%{element} (Z %{number})"),
        { element: symbol, number: String(atomicNumber(symbol) ?? "") },
        true,
    );
}

/** Adds what the field holds: the highlighted suggestion, else the exact symbol typed. */
function commit(): void {
    const typed = query.value.trim();
    const pick =
        showSuggestions.value && suggestions.value[activeIndex.value]
            ? suggestions.value[activeIndex.value]
            : props.symbols.find(
                  (symbol) => symbol.toLowerCase() === typed.toLowerCase(),
              );
    if (pick) {
        unknownSymbol.value = null;
        emit("add-element", { symbol: pick });
    } else if (typed !== "" && props.symbols.length > 0) {
        unknownSymbol.value = typed;
        return;
    }
    query.value = "";
    suggestionsOpen.value = false;
    activeIndex.value = 0;
}

function choose(symbol: string): void {
    unknownSymbol.value = null;
    emit("add-element", { symbol });
    query.value = "";
    suggestionsOpen.value = false;
    activeIndex.value = 0;
}

function onInput(event: Event): void {
    query.value = (event.target as HTMLInputElement).value;
    unknownSymbol.value = null;
    suggestionsOpen.value = true;
    activeIndex.value = 0;
}

function onKeydown(event: KeyboardEvent): void {
    const count = suggestions.value.length;
    if (event.key === "ArrowDown") {
        event.preventDefault();
        suggestionsOpen.value = true;
        activeIndex.value = count === 0 ? 0 : (activeIndex.value + 1) % count;
    } else if (event.key === "ArrowUp") {
        event.preventDefault();
        suggestionsOpen.value = true;
        activeIndex.value =
            count === 0 ? 0 : (activeIndex.value - 1 + count) % count;
    } else if (event.key === "Enter") {
        event.preventDefault();
        commit();
    } else if (event.key === "Escape" && suggestionsOpen.value) {
        event.preventDefault();
        suggestionsOpen.value = false;
    }
}
</script>

<template>
    <section
        class="xrf-strip"
        :aria-label="$gettext('XRF lens')"
    >
        <div class="picker">
            <label
                class="field"
                :for="inputId"
            >
                <span>{{ $gettext("Add an element") }}</span>
                <span class="combobox">
                    <input
                        :id="inputId"
                        type="text"
                        role="combobox"
                        autocomplete="off"
                        spellcheck="false"
                        maxlength="2"
                        aria-autocomplete="list"
                        :aria-expanded="showSuggestions ? 'true' : 'false'"
                        :aria-controls="listId"
                        :aria-activedescendant="
                            showSuggestions
                                ? `${listId}-${activeIndex}`
                                : undefined
                        "
                        :value="query"
                        @input="onInput"
                        @focus="suggestionsOpen = true"
                        @keydown="onKeydown"
                    />
                    <ul
                        v-show="showSuggestions"
                        :id="listId"
                        class="suggestions"
                        role="listbox"
                        :aria-label="$gettext('Elements')"
                    >
                        <li
                            v-for="(symbol, index) in suggestions"
                            :id="`${listId}-${index}`"
                            :key="symbol"
                            role="option"
                            :aria-selected="
                                index === activeIndex ? 'true' : 'false'
                            "
                            @pointerdown.prevent="choose(symbol)"
                        >
                            <span>{{ symbol }}</span>
                        </li>
                    </ul>
                </span>
            </label>
            <button
                type="button"
                class="table-toggle"
                :aria-expanded="tableOpen ? 'true' : 'false'"
                @click="tableOpen = !tableOpen"
            >
                <span>{{ $gettext("Periodic table") }}</span>
            </button>
            <p
                v-if="unknownSymbol !== null"
                class="unknown"
                role="status"
            >
                <span>{{ missingText(unknownSymbol) }}</span>
            </p>
        </div>
        <div
            v-if="tableOpen"
            class="mini-table"
            role="group"
            :aria-label="$gettext('Lens elements')"
        >
            <button
                v-for="cell in grid"
                :key="cell.symbol"
                type="button"
                class="cell"
                :style="cell.position"
                :aria-label="cellLabel(cell.symbol)"
                :aria-pressed="cell.pressed ? 'true' : 'false'"
                @click="emit('toggle-element', { symbol: cell.symbol })"
            >
                <span>{{ cell.symbol }}</span>
            </button>
        </div>
        <ul
            v-if="hasContent"
            class="lines"
            :aria-label="$gettext('XRF lines')"
        >
            <li
                v-for="element in elements"
                :key="`${element.kind}:${element.symbol}`"
                class="element"
                :data-kind="element.kind"
                :data-symbol="element.symbol"
            >
                <FocusSlotDot
                    v-if="element.slot !== null"
                    :number="element.slot"
                    size="small"
                />
                <strong class="symbol">{{ element.symbol }}</strong>
                <span
                    v-if="!element.known"
                    class="text"
                    >{{ missingText(element.symbol) }}</span
                >
                <span
                    v-else-if="element.lines.length > 0"
                    class="text"
                    >{{ linesText(element) }} keV</span
                >
                <span
                    v-else
                    class="text"
                    >{{ $gettext("No line in the energy range shown") }}</span
                >
                <span
                    v-if="element.declared"
                    class="declared"
                    >{{ declaredOf(element) }}</span
                >
                <button
                    v-if="element.kind === 'lens'"
                    type="button"
                    class="remove"
                    :aria-label="removeLabel(element.symbol)"
                    @click="emit('remove-element', { symbol: element.symbol })"
                >
                    <span aria-hidden="true">×</span>
                </button>
            </li>
            <li
                v-for="entry in declaredSlots"
                :key="`declared:${entry.slot}`"
                class="declared-slot"
            >
                <span>{{ declaredSlotText(entry) }}</span>
            </li>
            <li
                v-for="(overlap, index) in overlaps"
                :key="`overlap:${index}`"
                class="overlap"
            >
                <span>{{ overlapText(overlap) }}</span>
            </li>
        </ul>
    </section>
</template>

<style scoped>
.xrf-strip {
    display: grid;
    gap: 0.375rem;
    font-size: 0.8125rem;
    color: var(--ink);
}

.xrf-strip .picker {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem 0.5rem;
}

.xrf-strip .field {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    color: var(--ink-muted);
}

.xrf-strip .combobox {
    position: relative;
}

.xrf-strip input {
    inline-size: 4rem;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-family: var(--font-mono);
}

.xrf-strip .suggestions {
    position: absolute;
    inset-block-start: 100%;
    inset-inline-start: 0;
    z-index: 1100;
    display: grid;
    min-inline-size: 100%;
    margin: 0.125rem 0 0;
    padding: 0.25rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    box-shadow: 0 0.25rem 1rem color-mix(in srgb, var(--ink) 15%, transparent);
    list-style: none;
}

.xrf-strip .suggestions li {
    padding: 0.25rem 0.5rem;
    border-radius: 0.25rem;
    font-family: var(--font-mono);
    cursor: pointer;
}

.xrf-strip .suggestions li[aria-selected="true"] {
    background: var(--bg-alt);
}

.xrf-strip .table-toggle {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.625rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.xrf-strip .table-toggle[aria-expanded="true"] {
    border-color: var(--ink);
    background: var(--bg-alt);
}

.xrf-strip .unknown {
    margin: 0;
    color: var(--ink-muted);
}

.xrf-strip .mini-table {
    display: grid;
    grid-template-columns: repeat(18, minmax(1.5rem, 2rem));
    grid-template-rows: repeat(5, auto) 0.5rem repeat(2, auto);
    gap: 0.125rem;
    overflow-x: auto;
}

.xrf-strip .mini-table .cell {
    min-block-size: 1.5rem;
    padding: 0;
    border: 0.0625rem solid var(--border);
    border-radius: 0.1875rem;
    background: var(--bg-alt);
    color: var(--ink-muted);
    font: 0.6875rem var(--font-mono);
    cursor: pointer;
}

.xrf-strip .mini-table .cell[aria-pressed="true"] {
    border-color: var(--ink);
    background: var(--ink);
    color: var(--surface);
}

.xrf-strip .lines {
    display: grid;
    gap: 0.25rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.xrf-strip .element {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.125rem 0.5rem;
}

.xrf-strip .element[data-kind="preview"] {
    color: var(--ink-muted);
    font-style: italic;
}

.xrf-strip .element .symbol,
.xrf-strip .element .text {
    font-family: var(--font-mono);
}

.xrf-strip .element .declared,
.xrf-strip .declared-slot,
.xrf-strip .overlap {
    color: var(--ink-muted);
}

.xrf-strip .remove {
    min-inline-size: 1.5rem;
    min-block-size: 1.5rem;
    padding: 0;
    border: none;
    border-radius: 0.25rem;
    background: none;
    color: var(--ink-muted);
    font: inherit;
    cursor: pointer;
}

.xrf-strip .remove:hover {
    background: var(--bg-alt);
    color: var(--ink);
}

.xrf-strip input:focus-visible,
.xrf-strip .table-toggle:focus-visible,
.xrf-strip .mini-table .cell:focus-visible,
.xrf-strip .remove:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
