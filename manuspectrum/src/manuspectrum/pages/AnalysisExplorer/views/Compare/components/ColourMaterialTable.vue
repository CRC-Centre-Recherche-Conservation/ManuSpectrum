<script setup lang="ts">
import { useGettext } from "vue3-gettext";

import type { SynthesisPair } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * The colours × materials of the Selection's identified materials, one row
 * per pair: colour, material, elements (by symbol when they have one),
 * folios, best certainty, number of identified materials. A click on a row
 * toggles its pair as the filter; the material's button carries the same
 * toggle for the keyboard, named by the colour and the material, pressed
 * on the pair `pressed` names. A folio is named by its label when
 * `canvasLabels` knows it, the others are counted.
 */
const props = defineProps<{
    pairs: readonly SynthesisPair[];
    canvasLabels: ReadonlyMap<string, string>;
    pressed: readonly [string | null, string] | null;
}>();

const emit = defineEmits<{
    (
        event: "toggle",
        payload: { colour: string | null; material: string },
    ): void;
}>();

const { $gettext, $ngettext, interpolate } = useGettext();

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

function toggleLabel(pair: SynthesisPair): string {
    return interpolate(
        $gettext("%{colour}, %{material}"),
        {
            colour: pair.colour?.label.value ?? $gettext("No colour"),
            material: pair.material.label.value,
        },
        true,
    );
}

function toggle(pair: SynthesisPair): void {
    emit("toggle", { colour: colourId(pair), material: pair.material.id });
}
</script>

<template>
    <div class="colour-material-table">
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
                    v-for="pair in props.pairs"
                    :key="keyOf(pair)"
                    :class="{ 'is-pressed': isPressed(pair) }"
                    @click="toggle(pair)"
                >
                    <td>
                        <span
                            v-if="pair.colour"
                            :lang="pair.colour.label.lang"
                            >{{ pair.colour.label.value }}</span
                        >
                        <span
                            v-else
                            class="none"
                            >{{ $gettext("No colour stated") }}</span
                        >
                    </td>
                    <th scope="row">
                        <button
                            type="button"
                            :aria-label="toggleLabel(pair)"
                            :aria-pressed="isPressed(pair) ? 'true' : 'false'"
                        >
                            <span :lang="pair.material.label.lang">{{
                                pair.material.label.value
                            }}</span>
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
