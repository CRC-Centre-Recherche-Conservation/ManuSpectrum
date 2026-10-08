<script setup lang="ts">
import {
    computed,
    onBeforeUnmount,
    ref,
    useId,
    useTemplateRef,
    watch,
} from "vue";
import { useGettext } from "vue3-gettext";

import FocusSlotDot from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusSlotDot.vue";

import { useAnchoredPopover } from "@/manuspectrum/pages/AnalysisExplorer/composables/useAnchoredPopover.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { elementHue } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/element-colour.ts";
import { declaredText } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/declared.ts";
import {
    PERIODIC_TABLE,
    atomicNumber,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/periodic.ts";

import type {
    StripDeclaredSlot,
    StripElement,
    StripInstrumentPeak,
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
 * elements are the reader's own list; they never enter the focus. The
 * suggestions and the periodic table are popovers in the top layer, under
 * their input and button (`useAnchoredPopover`): Escape or a press outside
 * closes the table and the focus goes back to its button.
 */
const props = defineProps<{
    elements: readonly StripElement[];
    declaredSlots: readonly StripDeclaredSlot[];
    overlaps: readonly StripOverlap[];
    /** The instrument peaks the chart's bottom ticks draw, one per label and energy. */
    instrument: readonly StripInstrumentPeak[];
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
const tableId = useId();
const input = useTemplateRef<HTMLInputElement>("input");
const listbox = useTemplateRef<HTMLElement>("listbox");
const toggle = useTemplateRef<HTMLButtonElement>("toggle");
const tablePopover = useTemplateRef<HTMLElement>("tablePopover");
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
const { style: listStyle } = useAnchoredPopover(
    showSuggestions,
    listbox,
    input,
);
const { style: tableStyle } = useAnchoredPopover(
    tableOpen,
    tablePopover,
    toggle,
);
const hasContent = computed(
    () =>
        props.elements.length > 0 ||
        props.declaredSlots.length > 0 ||
        props.overlaps.length > 0 ||
        props.instrument.length > 0,
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

function instrumentText(): string {
    const peaks = props.instrument
        .map(
            (peak) =>
                `${peak.label} ${energy(peak.energy)} keV (${
                    peak.everywhere
                        ? $gettext("all")
                        : peak.slots.map(slotLabel).join(", ")
                })`,
        )
        .join(" · ");
    return `${$gettext("Instrument peaks")}: ${peaks}`;
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

function openSuggestions(): void {
    tableOpen.value = false;
    suggestionsOpen.value = true;
}

function onInput(event: Event): void {
    query.value = (event.target as HTMLInputElement).value;
    unknownSymbol.value = null;
    openSuggestions();
    activeIndex.value = 0;
}

function closeTable(returnFocus: boolean): void {
    tableOpen.value = false;
    if (returnFocus) toggle.value?.focus();
}

function onPointerDown(event: PointerEvent): void {
    const target = event.target;
    if (!(target instanceof Node)) return;
    if (tablePopover.value?.contains(target) || toggle.value?.contains(target))
        return;
    closeTable(false);
}

/** Escape closes the table, unless the field's own Escape just closed the suggestions. */
function onEscape(event: KeyboardEvent): void {
    if (!tableOpen.value || event.defaultPrevented) return;
    event.preventDefault();
    closeTable(true);
}

watch(tableOpen, (isOpen) => {
    if (isOpen) {
        suggestionsOpen.value = false;
        document.addEventListener("pointerdown", onPointerDown);
    } else {
        document.removeEventListener("pointerdown", onPointerDown);
    }
});

onBeforeUnmount(() =>
    document.removeEventListener("pointerdown", onPointerDown),
);

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
        @keydown.esc="onEscape"
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
                        ref="input"
                        type="text"
                        role="combobox"
                        autocomplete="off"
                        spellcheck="false"
                        maxlength="2"
                        aria-autocomplete="list"
                        aria-haspopup="listbox"
                        :aria-expanded="showSuggestions ? 'true' : 'false'"
                        :aria-controls="listId"
                        :aria-activedescendant="
                            showSuggestions
                                ? `${listId}-${activeIndex}`
                                : undefined
                        "
                        :value="query"
                        @input="onInput"
                        @focus="openSuggestions"
                        @blur="suggestionsOpen = false"
                        @keydown="onKeydown"
                    />
                    <ul
                        v-show="showSuggestions"
                        :id="listId"
                        ref="listbox"
                        popover="manual"
                        class="suggestions"
                        :style="listStyle"
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
                ref="toggle"
                type="button"
                class="table-toggle"
                data-popover="xrf-table"
                :aria-expanded="tableOpen ? 'true' : 'false'"
                :aria-controls="tableOpen ? tableId : undefined"
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
            :id="tableId"
            ref="tablePopover"
            popover="manual"
            class="mini-table"
            :style="tableStyle"
            role="group"
            :aria-label="$gettext('Lens elements')"
        >
            <button
                v-for="cell in grid"
                :key="cell.symbol"
                type="button"
                class="cell"
                :style="cell.position"
                :data-hue="elementHue(cell.symbol)"
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
                :data-hue="
                    element.slot === null
                        ? elementHue(element.symbol)
                        : undefined
                "
            >
                <FocusSlotDot
                    v-if="element.slot !== null"
                    :number="element.slot"
                    size="small"
                />
                <span
                    v-else
                    class="swatch"
                    aria-hidden="true"
                ></span>
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
                v-if="instrument.length > 0"
                class="instrument"
            >
                <span>{{ instrumentText() }}</span>
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
    position: fixed;
    inset: auto;
    display: grid;
    align-content: start;
    inline-size: max-content;
    min-inline-size: var(--anchor-width, 0);
    max-block-size: 12rem;
    margin: 0;
    padding: 0.25rem;
    overflow-y: auto;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
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
    position: fixed;
    inset: auto;
    display: grid;
    grid-template-columns: repeat(18, minmax(1.5rem, 2rem));
    grid-template-rows: repeat(5, auto) 0.5rem repeat(2, auto);
    gap: 0.125rem;
    inline-size: max-content;
    max-inline-size: calc(100vw - 1rem);
    margin: 0;
    padding: 0.5rem;
    overflow: auto;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    box-shadow: 0 0.25rem 1rem color-mix(in srgb, var(--ink) 15%, transparent);
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
    border-color: var(--chip);
    background: var(--chip);
    color: var(--surface);
}

.xrf-strip [data-hue="0"] {
    --chip: var(--element-1);
}

.xrf-strip [data-hue="1"] {
    --chip: var(--element-2);
}

.xrf-strip [data-hue="2"] {
    --chip: var(--element-3);
}

.xrf-strip [data-hue="3"] {
    --chip: var(--element-4);
}

.xrf-strip [data-hue="4"] {
    --chip: var(--element-5);
}

.xrf-strip [data-hue="5"] {
    --chip: var(--element-6);
}

.xrf-strip [data-hue="6"] {
    --chip: var(--element-7);
}

.xrf-strip [data-hue="7"] {
    --chip: var(--element-8);
}

.xrf-strip [data-hue="8"] {
    --chip: var(--element-9);
}

.xrf-strip [data-hue="9"] {
    --chip: var(--element-10);
}

.xrf-strip .swatch {
    align-self: center;
    inline-size: 0.25rem;
    block-size: 1rem;
    border-radius: 0.125rem;
    background: var(--chip);
}

.xrf-strip .element[data-kind="lens"] .symbol {
    color: var(--chip);
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
.xrf-strip .instrument,
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
