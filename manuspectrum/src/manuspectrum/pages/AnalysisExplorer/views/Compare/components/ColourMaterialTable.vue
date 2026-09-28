<script setup lang="ts">
import { useId } from "vue";
import { useGettext } from "vue3-gettext";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { pairNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { SynthesisPair } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * The colours × materials of the Selection's identified materials, one row
 * per pair: colour, material, elements (by symbol when they have one),
 * folios, best certainty, number of identified materials. A click on a row
 * adds its pair (`pair:`) to the linked selection of Compare or removes it;
 * the material's button carries the same toggle for the keyboard, named by
 * the row's visible colour and material cells (each in its own language),
 * pressed while the pair is selected. A row is marked by how its pair
 * stands to the selection and to the node a mouse previews. A folio is
 * named by its label when `canvasLabels` knows it, the others are counted.
 */
const props = defineProps<{
    pairs: readonly SynthesisPair[];
    canvasLabels: ReadonlyMap<string, string>;
    /** Marks every toggle `aria-disabled` and inert (a stale table while the next one is read). */
    disabled?: boolean;
}>();

const { $gettext, $ngettext, interpolate } = useGettext();
const baseId = useId();
const marks = useLinkedMarks();

function colourId(pair: SynthesisPair): string | null {
    return pair.colour?.id ?? null;
}

function keyOf(pair: SynthesisPair): string {
    return `${colourId(pair) ?? "-"}|${pair.material.id}`;
}

function nodeOf(pair: SynthesisPair): string {
    return pairNode(colourId(pair), pair.material.id);
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
    if (!props.disabled) marks.toggle(nodeOf(pair));
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
                    :data-rel="marks.rel(nodeOf(pair))"
                    :data-preview="marks.previewRel(nodeOf(pair))"
                    @click="toggle(pair)"
                    @pointerenter="marks.enter(nodeOf(pair), $event)"
                    @pointerleave="marks.leave($event)"
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
                            :aria-pressed="marks.pressed(nodeOf(pair))"
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

.colour-material-table tbody tr:hover {
    background: var(--bg-alt);
}

.colour-material-table tbody tr > :first-child {
    position: relative;
}

.colour-material-table tbody tr[data-rel="self"],
.colour-material-table tbody tr[data-rel="direct"],
.colour-material-table tbody tr[data-rel="evidence"] {
    background: var(--linked-tint, var(--bg-alt));
}

.colour-material-table tbody tr[data-rel="self"] > :first-child::before,
.colour-material-table tbody tr[data-rel="direct"] > :first-child::before,
.colour-material-table tbody tr[data-rel="evidence"] > :first-child::before {
    position: absolute;
    inset-block: 0;
    inset-inline-start: 0;
    border-inline-start: var(--linked-bar, 0.1875rem) solid
        var(--linked-mark, var(--blue-text));
    content: "";
}

.colour-material-table tbody tr[data-rel="evidence"] > :first-child::before {
    border-inline-start-style: dashed;
}

.colour-material-table tbody tr[data-rel="none"],
.colour-material-table tbody tr[data-rel="none"] button {
    border-color: var(--border);
    color: var(--ink-muted);
}

.colour-material-table tbody tr[data-preview] {
    outline: 0.125rem dashed var(--linked-mark, var(--blue-text));
    outline-offset: -0.125rem;
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
    outline: 0.125rem solid var(--linked-mark, var(--blue-text));
    outline-offset: 0.0625rem;
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
