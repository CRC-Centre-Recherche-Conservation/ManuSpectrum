<script setup lang="ts">
import {
    computed,
    inject,
    onMounted,
    ref,
    useId,
    useTemplateRef,
    watch,
} from "vue";
import { useGettext } from "vue3-gettext";

import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { declaredText } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/declared.ts";

import type {
    DeclaredElement,
    DeclaredParts,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/declared.ts";
import type {
    Candidate,
    Confirmation,
    ElementCandidate,
    InstrumentCandidate,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/identify.ts";

const MAX_SHOWN = 8;
const ENERGY_DIGITS = 2;
/** The energy field keeps this many decimals (keV): a channel is never finer. */
const FIELD_DECIMALS = 1000;
/** A moved energy is kept to the micro-keV, so stepping never drifts into float noise. */
const MOVE_DECIMALS = 1e6;

/**
 * The peak identifier of an XRF window: a non-modal region under the toolbar
 * that lists what a peak at an energy may be (`candidates`, best first), the
 * spectrum it was read on, an energy field and two buttons that move it by
 * one channel. An element row gives the line, its energy, what its other
 * lines confirm and what the Selection declares; « Pin Pb » toggles the
 * element in the focus (offered only when the element is a node of the
 * graph) and « Show Pb lines » toggles it in the lens. It pins nothing by
 * itself. Escape closes it (`close`); opening, and every move, announce the
 * count of candidates. The count of rows is capped at eight until « Show
 * all ».
 */
const props = defineProps<{
    /** The energy checked (keV). */
    energy: number;
    /** « A2 · file »: the spectrum the peak was read on. */
    curveName: string;
    candidates: readonly Candidate[];
    /** The tube voltage of that spectrum; null when unknown. */
    kV: number | null;
    /** The spacing of the channels (keV): the step of the field and of the arrows. */
    channel: number;
    /** The match tolerance around `energy` (keV). */
    tolerance: number;
    lang: string;
    /** Whether the focus can hold the element (it is an `el:` node of the graph). */
    pinnable: (symbol: string) => boolean;
    pinned: (symbol: string) => boolean;
    lensSymbols: readonly string[];
    /** The parts of the « declared … » sentence of an entry, read from the spectrum's analysis. */
    declaredParts: (entry: DeclaredElement) => DeclaredParts | null;
}>();

const emit = defineEmits<{
    (event: "move", payload: { energy: number }): void;
    (event: "close"): void;
    (event: "toggle-pin", payload: { symbol: string }): void;
    (event: "toggle-lens", payload: { symbol: string }): void;
}>();

const { $gettext, $ngettext, interpolate } = useGettext();
const announce = inject(ANNOUNCE_KEY, () => undefined);

const headingId = useId();
const fieldId = useId();
const field = useTemplateRef<HTMLInputElement>("field");
const showAll = ref(false);

const numbers = computed(
    () =>
        new Intl.NumberFormat(props.lang, {
            minimumFractionDigits: ENERGY_DIGITS,
            maximumFractionDigits: ENERGY_DIGITS,
        }),
);
const voltage = computed(
    () => new Intl.NumberFormat(props.lang, { maximumFractionDigits: 1 }),
);
const heading = computed(() =>
    interpolate(
        $gettext("Candidates at %{energy} keV (± %{tolerance})"),
        {
            energy: numbers.value.format(props.energy),
            tolerance: numbers.value.format(props.tolerance),
        },
        true,
    ),
);
const shown = computed(() =>
    showAll.value ? props.candidates : props.candidates.slice(0, MAX_SHOWN),
);
const fieldValue = computed(
    () => Math.round(props.energy * FIELD_DECIMALS) / FIELD_DECIMALS,
);

watch(
    () => props.energy,
    () => {
        announce(
            interpolate(
                $ngettext(
                    "%{n} candidate at %{energy} keV",
                    "%{n} candidates at %{energy} keV",
                    props.candidates.length,
                ),
                {
                    n: props.candidates.length,
                    energy: numbers.value.format(props.energy),
                },
                true,
            ),
        );
    },
    { immediate: true },
);

onMounted(() => field.value?.focus());

function energyText(value: number): string {
    return numbers.value.format(value);
}

function confirmationText(confirmation: Confirmation): string {
    const values = {
        line: confirmation.line.label,
        energy: energyText(confirmation.line.energy),
    };
    switch (confirmation.state) {
        case "present":
            return interpolate(
                $gettext("%{line} %{energy} present"),
                values,
                true,
            );
        case "absent":
            return interpolate(
                $gettext("%{line} %{energy} absent"),
                values,
                true,
            );
        case "unresolved":
            return interpolate(
                $gettext("%{line} %{energy} too close to tell"),
                values,
                true,
            );
        case "out-of-range":
            return interpolate(
                $gettext("%{line} %{energy} out of range"),
                values,
                true,
            );
        default:
            return `${values.line} ${values.energy} ${interpolate(
                $gettext("not excited at %{kv} kV"),
                { kv: props.kV === null ? "" : voltage.value.format(props.kV) },
                true,
            )}`;
    }
}

function declaredOf(candidate: ElementCandidate): string {
    if (!candidate.declared) return "";
    const parts = props.declaredParts(candidate.declared.entry);
    return parts ? declaredText(parts, { $gettext, interpolate }) : "";
}

function instrumentText(candidate: InstrumentCandidate): string {
    const { peak } = candidate;
    const anode = `${peak.source ?? ""} ${peak.line ?? ""}`.trim();
    switch (peak.kind) {
        case "rayleigh":
            return `${anode} · ${$gettext("Rayleigh scatter")}`;
        case "compton":
            return `${anode} · ${$gettext("Compton scatter")}`;
        case "escape":
            return interpolate(
                $gettext("Escape of %{energy} keV"),
                { energy: energyText(peak.parents[0] ?? peak.energy) },
                true,
            );
        case "sum":
            return interpolate(
                $gettext("Sum %{a} + %{b} keV"),
                {
                    a: energyText(peak.parents[0] ?? peak.energy),
                    b: energyText(peak.parents[1] ?? peak.energy),
                },
                true,
            );
        default:
            return interpolate(
                $gettext("Tube voltage limit (%{kv} kV)"),
                { kv: energyText(peak.energy) },
                true,
            );
    }
}

function pinLabel(symbol: string): string {
    return interpolate($gettext("Pin %{element}"), { element: symbol }, true);
}

function linesLabel(symbol: string): string {
    return interpolate(
        $gettext("Show %{element} lines"),
        { element: symbol },
        true,
    );
}

function moveBy(channels: number): void {
    emit("move", {
        energy:
            Math.round(
                (props.energy + channels * props.channel) * MOVE_DECIMALS,
            ) / MOVE_DECIMALS,
    });
}

function onField(event: Event): void {
    const value = Number((event.target as HTMLInputElement).value);
    if (
        Number.isFinite(value) &&
        (event.target as HTMLInputElement).value !== ""
    ) {
        emit("move", { energy: value });
    }
}

function onKeydown(event: KeyboardEvent): void {
    if (event.key !== "Escape") return;
    event.preventDefault();
    emit("close");
}
</script>

<template>
    <section
        class="peak-identifier"
        role="dialog"
        :aria-labelledby="headingId"
        @keydown="onKeydown"
    >
        <h3
            :id="headingId"
            class="heading"
        >
            <span>{{ heading }}</span>
        </h3>
        <p class="checked">
            <span>{{ $gettext("Spectrum checked") }}</span
            ><span>: {{ curveName }}</span>
        </p>
        <div class="energy">
            <label :for="fieldId">
                <span>{{ $gettext("Energy (keV)") }}</span>
            </label>
            <button
                type="button"
                data-action="lower"
                :aria-label="$gettext('Lower the energy by one channel')"
                @click="moveBy(-1)"
            >
                <span aria-hidden="true">←</span>
            </button>
            <input
                :id="fieldId"
                ref="field"
                type="number"
                :step="channel > 0 ? channel : 'any'"
                :value="fieldValue"
                @change="onField"
            />
            <button
                type="button"
                data-action="raise"
                :aria-label="$gettext('Raise the energy by one channel')"
                @click="moveBy(1)"
            >
                <span aria-hidden="true">→</span>
            </button>
        </div>
        <p
            v-if="candidates.length === 0"
            class="none"
        >
            <span>{{ $gettext("No candidate within the tolerance") }}</span>
        </p>
        <ul
            v-else
            class="candidates"
        >
            <template
                v-for="(candidate, index) in shown"
                :key="
                    candidate.type === 'element'
                        ? `el:${candidate.symbol}`
                        : `in:${index}`
                "
            >
                <li
                    v-if="candidate.type === 'element'"
                    class="candidate element"
                    :data-symbol="candidate.symbol"
                >
                    <span class="symbol">{{ candidate.symbol }}</span>
                    <span class="line">
                        {{ candidate.line.label }}
                        {{ energyText(candidate.line.energy) }}
                    </span>
                    <span
                        v-for="confirmation in candidate.confirmations"
                        :key="confirmation.line.name"
                        class="confirmation"
                        :data-state="confirmation.state"
                    >
                        {{ confirmationText(confirmation) }}
                    </span>
                    <span
                        v-if="declaredOf(candidate) !== ''"
                        class="declared"
                    >
                        {{ declaredOf(candidate) }}
                    </span>
                    <span class="actions">
                        <button
                            v-if="pinnable(candidate.symbol)"
                            type="button"
                            data-action="pin"
                            :aria-pressed="
                                pinned(candidate.symbol) ? 'true' : 'false'
                            "
                            @click="
                                emit('toggle-pin', { symbol: candidate.symbol })
                            "
                        >
                            <span>{{ pinLabel(candidate.symbol) }}</span>
                        </button>
                        <button
                            type="button"
                            data-action="lines"
                            :aria-pressed="
                                lensSymbols.includes(candidate.symbol)
                                    ? 'true'
                                    : 'false'
                            "
                            @click="
                                emit('toggle-lens', {
                                    symbol: candidate.symbol,
                                })
                            "
                        >
                            <span>{{ linesLabel(candidate.symbol) }}</span>
                        </button>
                    </span>
                </li>
                <li
                    v-else
                    class="candidate instrument"
                    :data-kind="candidate.peak.kind"
                >
                    <span>{{ instrumentText(candidate) }}</span>
                </li>
            </template>
        </ul>
        <button
            v-if="!showAll && candidates.length > MAX_SHOWN"
            type="button"
            class="show-all"
            @click="showAll = true"
        >
            <span>{{
                interpolate(
                    $gettext("Show all (%{n})"),
                    { n: String(candidates.length) },
                    true,
                )
            }}</span>
        </button>
        <p class="footer">
            <span>{{
                $gettext("Indications only: the analyst decides.")
            }}</span>
        </p>
    </section>
</template>

<style scoped>
.peak-identifier {
    display: grid;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font-size: 0.8125rem;
}

.peak-identifier .heading {
    margin: 0;
    font-size: 0.875rem;
    font-weight: 600;
}

.peak-identifier .checked,
.peak-identifier .none,
.peak-identifier .footer {
    margin: 0;
    color: var(--ink-muted);
}

.peak-identifier .energy {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.375rem;
}

.peak-identifier .energy input {
    inline-size: 6rem;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-family: var(--font-mono);
}

.peak-identifier button {
    min-block-size: var(--explorer-target, 2.75rem);
    min-inline-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.625rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.peak-identifier button[aria-pressed="true"] {
    border-color: var(--ink);
    background: var(--bg-alt);
    font-weight: 600;
}

.peak-identifier .candidates {
    display: grid;
    gap: 0.375rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.peak-identifier .candidate {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.125rem 0.5rem;
}

.peak-identifier .candidate .symbol,
.peak-identifier .candidate .line {
    font-family: var(--font-mono);
}

.peak-identifier .candidate .declared,
.peak-identifier .candidate .confirmation {
    color: var(--ink-muted);
}

.peak-identifier .candidate .actions {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    margin-inline-start: auto;
}

.peak-identifier button:focus-visible,
.peak-identifier input:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
