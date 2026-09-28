<script setup lang="ts">
import { useId } from "vue";
import { useGettext } from "vue3-gettext";

import type { SynthesisPair } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * The colours × materials of the Selection's identified materials, one row
 * per pair: colour, material, elements (by symbol when they have one),
 * folios, best certainty, number of identified materials. A click on a row
 * toggles its pair as the filter; the material's button carries the same
 * toggle for the keyboard, named by the row's visible colour and material
 * cells (each in its own language), pressed on the pair `pressed` names. A folio is named by its label when
 * `canvasLabels` knows it, the others are counted.
 */
const props = defineProps<{
    pairs: readonly SynthesisPair[];
    canvasLabels: ReadonlyMap<string, string>;
    pressed: readonly [string | null, string] | null;
    /** Marks every toggle `aria-disabled` (a stale table while the next one is read). */
    disabled?: boolean;
}>();

const emit = defineEmits<{
    (
        event: "toggle",
        payload: { colour: string | null; material: string },
    ): void;
}>();

const { $gettext, $ngettext, interpolate } = useGettext();
const baseId = useId();

function colourId(pair: SynthesisPair): string | null {
    return pair.colour?.id ?? null;
}

function keyOf(pair: SynthesisPair): string {
    return `${colourId(pair) ?? "-"}|${pair.material.id}`;
}

function isPressed(pair: SynthesisPair): boolean {
    return (
        props.pressed !== null &&
        props.pressed[0] === colourId(pair) &&
        props.pressed[1] === pair.material.id
    );
}

function elementsText(pair: SynthesisPair): string {
    return pair.elements
        .map((element) => element.symbol ?? element.label.value)
        .join(", ");
}

function foliosText(pair: SynthesisPair): string {
    const named = pair.canvases.flatMap((canvas) => {
        const label = props.canvasLabels.get(canvas);
        return label ? [label] : [];
    });
    const others = pair.canvases.length - named.length;
    if (others === 0) return named.join(", ");
    const counted = interpolate(
        named.length > 0
            ? $ngettext("%{n} other folio", "%{n} other folios", others)
            : $ngettext("%{n} folio", "%{n} folios", others),
        { n: others },
        true,
    );
    return [...named, counted].join(", ");
}

function colourCellId(index: number): string {
    return `${baseId}-colour-${index}`;
}

function materialCellId(index: number): string {
    return `${baseId}-material-${index}`;
}

function toggleLabelledBy(index: number): string {
    return `${colourCellId(index)} ${materialCellId(index)}`;
}

function toggle(pair: SynthesisPair): void {
    emit("toggle", { colour: colourId(pair), material: pair.material.id });
}
</script>

<template>
    <div
        class="colour-material-table"
        :class="{ 'is-disabled': props.disabled }"
    >
        <table>
            <thead>
                <tr>
                    <th scope="col">
                        <span>{{ $gettext("Colour") }}</span>
                    </th>
                    <th scope="col">
                        <span>{{ $gettext("Material") }}</span>
                    </th>
                    <th scope="col">
                        <span>{{ $gettext("Elements") }}</span>
                    </th>
                    <th scope="col">
                        <span>{{ $gettext("Folios") }}</span>
                    </th>
                    <th scope="col">
                        <span>{{ $gettext("Best certainty") }}</span>
                    </th>
                    <th scope="col">
                        <span>{{ $gettext("Identified materials") }}</span>
                    </th>
                </tr>
            </thead>
            <tbody>
                <tr
                    v-for="(pair, index) in props.pairs"
                    :key="keyOf(pair)"
                    :class="{ 'is-pressed': isPressed(pair) }"
                    @click="toggle(pair)"
                >
                    <td>
                        <span
                            v-if="pair.colour"
                            :id="colourCellId(index)"
                            :lang="pair.colour.label.lang"
                            >{{ pair.colour.label.value }}</span
                        >
                        <span
                            v-else
                            :id="colourCellId(index)"
                            class="none"
                            >{{ $gettext("No colour stated") }}</span
                        >
                    </td>
                    <th scope="row">
                        <button
                            type="button"
                            :aria-labelledby="toggleLabelledBy(index)"
                            :aria-pressed="isPressed(pair) ? 'true' : 'false'"
                            :aria-disabled="props.disabled ? 'true' : undefined"
                        >
                            <span
                                :id="materialCellId(index)"
                                :lang="pair.material.label.lang"
                                >{{ pair.material.label.value }}</span
                            >
                        </button>
                    </th>
                    <td>
                        <span>{{ elementsText(pair) }}</span>
                    </td>
                    <td>
                        <span>{{ foliosText(pair) }}</span>
                    </td>
                    <td>
                        <span
                            v-if="pair.confidenceBest"
                            :lang="pair.confidenceBest.label.lang"
                            >{{ pair.confidenceBest.label.value }}</span
                        >
                    </td>
                    <td class="count">
                        <span>{{ pair.count }}</span>
                    </td>
                </tr>
            </tbody>
        </table>
    </div>
</template>

<style scoped>
.colour-material-table {
    overflow-x: auto;
}

.colour-material-table table {
    inline-size: 100%;
    border-collapse: collapse;
    font-size: 0.8125rem;
}

.colour-material-table th,
.colour-material-table td {
    padding: 0.25rem 0.5rem;
    border-block-end: 0.0625rem solid var(--border);
    text-align: start;
    vertical-align: middle;
}

.colour-material-table thead th {
    color: var(--ink-muted);
    font-weight: 600;
    white-space: nowrap;
}

.colour-material-table tbody tr {
    cursor: pointer;
}

.colour-material-table tbody tr:hover,
.colour-material-table tbody tr.is-pressed {
    background: var(--bg-alt);
}

.colour-material-table button {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-weight: 600;
    text-align: start;
    cursor: pointer;
}

.colour-material-table button[aria-pressed="true"] {
    border-color: var(--ink);
    background: var(--ink);
    color: var(--surface);
}

.colour-material-table.is-disabled tbody tr,
.colour-material-table button[aria-disabled="true"] {
    cursor: default;
}

.colour-material-table button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.colour-material-table .none {
    color: var(--ink-muted);
}

.colour-material-table .count {
    font-family: var(--font-mono);
}
</style>
