<script setup lang="ts">
import { computed, inject } from "vue";
import { useGettext } from "vue3-gettext";

import HeatLegend from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/HeatLegend.vue";
import TechniqueCode from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/TechniqueCode.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { FOLIO_REQUEST_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { heatLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/heat.ts";
import {
    canvasNode,
    cellNode,
    techniqueNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type {
    SynthesisCoverage,
    Technique,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * The coverage matrix of the Selection: its canvases in rows, techniques in
 * columns (those the rows shown count, headed by their code, the full name
 * read and shown on hover), the number of analyses in each cell, shaded on
 * the blue heat ramp (`heatLevel`, the legend under the table says what the
 * number counts). A cell with analyses is a
 * toggle button naming its canvas, technique and count (`cell:`); a row's
 * folio (`cv:`) and a column's technique (`tech:`) are toggles too. A
 * click adds the node to the linked selection of Compare or removes it; a
 * toggle is pressed while its node is selected. A row's folio or a cell
 * clicked also asks the folio image tools to show that folio
 * (`FOLIO_REQUEST_KEY`). Rows, headers and cells
 * are marked by how they stand to the selection and to the node a mouse
 * previews; an unlinked cell keeps a quarter of its shade. An empty cell
 * says it holds no published analysis.
 */
const props = defineProps<{
    rows: readonly SynthesisCoverage[];
    techniques: readonly Technique[];
    /** Marks every toggle `aria-disabled` and inert (a stale matrix while the next one is read). */
    disabled?: boolean;
}>();

const { $gettext, $ngettext, interpolate } = useGettext();
const marks = useLinkedMarks();
const folios = inject(FOLIO_REQUEST_KEY, null);

const shownTechniques = computed(() =>
    props.techniques.filter((technique) =>
        props.rows.some((row) => countOf(row, technique) > 0),
    ),
);

const maxCount = computed(() =>
    Math.max(
        0,
        ...props.rows.flatMap((row) =>
            shownTechniques.value.map((technique) => countOf(row, technique)),
        ),
    ),
);

function countOf(row: SynthesisCoverage, technique: Technique): number {
    return row.counts[technique.id] ?? 0;
}

function toggle(node: string): void {
    if (!props.disabled) marks.toggle(node);
}

/** Toggles `node` and shows the folio of `row` in the folio image tools. */
function toggleOnFolio(node: string, row: SynthesisCoverage): void {
    if (props.disabled) return;
    marks.toggle(node);
    folios?.show(row.canvas, row.label);
}

function cellLabel(row: SynthesisCoverage, technique: Technique): string {
    const count = countOf(row, technique);
    return interpolate(
        $ngettext(
            "%{canvas}, %{technique}: %{n} analysis",
            "%{canvas}, %{technique}: %{n} analyses",
            count,
        ),
        { canvas: row.label, technique: technique.label.value, n: count },
        true,
    );
}
</script>

<template>
    <div class="coverage-matrix">
        <div class="scroll">
            <table>
                <thead>
                    <tr>
                        <th scope="col">
                            <span>{{ $gettext("Folio") }}</span>
                        </th>
                        <th
                            v-for="technique in shownTechniques"
                            :key="technique.id"
                            scope="col"
                            :data-rel="marks.rel(techniqueNode(technique.id))"
                            :data-preview="
                                marks.previewRel(techniqueNode(technique.id))
                            "
                        >
                            <button
                                type="button"
                                class="technique"
                                :title="technique.label.value"
                                :aria-pressed="
                                    marks.pressed(techniqueNode(technique.id))
                                "
                                :aria-disabled="
                                    props.disabled ? 'true' : undefined
                                "
                                @click="toggle(techniqueNode(technique.id))"
                                @pointerenter="
                                    marks.enter(
                                        techniqueNode(technique.id),
                                        $event,
                                    )
                                "
                                @pointerleave="marks.leave($event)"
                            >
                                <TechniqueCode
                                    :code="technique.code"
                                    :colour="technique.colour"
                                />
                                <span
                                    class="name visually-hidden"
                                    :lang="technique.label.lang"
                                    >{{ technique.label.value }}</span
                                >
                            </button>
                        </th>
                    </tr>
                </thead>
                <tbody>
                    <tr
                        v-for="row in props.rows"
                        :key="row.canvas"
                        :data-rel="marks.rel(canvasNode(row.canvas))"
                        :data-preview="marks.previewRel(canvasNode(row.canvas))"
                    >
                        <th scope="row">
                            <button
                                type="button"
                                class="folio"
                                :aria-pressed="
                                    marks.pressed(canvasNode(row.canvas))
                                "
                                :aria-disabled="
                                    props.disabled ? 'true' : undefined
                                "
                                @click="
                                    toggleOnFolio(canvasNode(row.canvas), row)
                                "
                                @pointerenter="
                                    marks.enter(canvasNode(row.canvas), $event)
                                "
                                @pointerleave="marks.leave($event)"
                            >
                                <span>{{ row.label }}</span>
                            </button>
                        </th>
                        <td
                            v-for="technique in shownTechniques"
                            :key="technique.id"
                        >
                            <button
                                v-if="countOf(row, technique) > 0"
                                type="button"
                                class="cell"
                                :data-heat="
                                    heatLevel(countOf(row, technique), maxCount)
                                "
                                :data-rel="
                                    marks.rel(
                                        cellNode(row.canvas, technique.id),
                                    )
                                "
                                :data-preview="
                                    marks.previewRel(
                                        cellNode(row.canvas, technique.id),
                                    )
                                "
                                :aria-label="cellLabel(row, technique)"
                                :aria-pressed="
                                    marks.pressed(
                                        cellNode(row.canvas, technique.id),
                                    )
                                "
                                :aria-disabled="
                                    props.disabled ? 'true' : undefined
                                "
                                @click="
                                    toggleOnFolio(
                                        cellNode(row.canvas, technique.id),
                                        row,
                                    )
                                "
                                @pointerenter="
                                    marks.enter(
                                        cellNode(row.canvas, technique.id),
                                        $event,
                                    )
                                "
                                @pointerleave="marks.leave($event)"
                            >
                                <span>{{ countOf(row, technique) }}</span>
                            </button>
                            <template v-else>
                                <span
                                    class="none"
                                    aria-hidden="true"
                                    >·</span
                                >
                                <span class="visually-hidden">{{
                                    $gettext("No published analysis")
                                }}</span>
                            </template>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
        <HeatLegend
            :caption="
                $gettext(
                    'Analyses of the Selection on the folio with the technique',
                )
            "
            :max="maxCount"
        />
    </div>
</template>

<style scoped>
.coverage-matrix {
    display: grid;
    gap: 0.75rem;
}

.coverage-matrix .scroll {
    position: relative;
    overflow-x: auto;
}

.coverage-matrix table {
    inline-size: 100%;
    border-collapse: separate;
    border-spacing: 0.25rem;
    font-size: 0.8125rem;
}

.coverage-matrix th,
.coverage-matrix td {
    padding: 0;
    text-align: center;
}

.coverage-matrix thead th {
    color: var(--ink-muted);
    font-weight: 600;
    white-space: nowrap;
}

.coverage-matrix thead th:first-child,
.coverage-matrix tbody th {
    padding-inline-end: 0.5rem;
    text-align: start;
}

.coverage-matrix thead th:first-child {
    font-size: 0.6875rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.coverage-matrix tbody th {
    font-family: var(--font-mono);
    font-weight: 600;
    white-space: nowrap;
}

.coverage-matrix .technique,
.coverage-matrix .folio {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.375rem;
    border: 0.0625rem solid transparent;
    border-radius: 0.25rem;
    background: none;
    color: inherit;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
}

.coverage-matrix .technique:hover,
.coverage-matrix .folio:hover {
    border-color: var(--border-hover);
}

.coverage-matrix .cell {
    --cell-heat: var(--heat-1);
    --cell-on: var(--heat-1-on);

    inline-size: 100%;
    min-inline-size: var(--explorer-target, 2.75rem);
    min-block-size: var(--explorer-target, 2.75rem);
    border: none;
    border-radius: 0.25rem;
    background: var(--cell-heat);
    color: var(--cell-on);
    font: 600 0.8125rem var(--font-mono);
    font-variant-numeric: tabular-nums;
    cursor: pointer;
}

.coverage-matrix .cell[data-heat="2"] {
    --cell-heat: var(--heat-2);
    --cell-on: var(--heat-2-on);
}

.coverage-matrix .cell[data-heat="3"] {
    --cell-heat: var(--heat-3);
    --cell-on: var(--heat-3-on);
}

.coverage-matrix .cell[data-heat="4"] {
    --cell-heat: var(--heat-4);
    --cell-on: var(--heat-4-on);
}

.coverage-matrix button[aria-pressed="true"] {
    border-color: var(--ink);
    outline: 0.125rem solid var(--linked-mark, var(--blue-text));
    outline-offset: 0.0625rem;
}

.coverage-matrix .cell[aria-pressed="true"] {
    background: var(--ink);
    color: var(--surface);
}

.coverage-matrix button[aria-disabled="true"] {
    cursor: default;
}

.coverage-matrix button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.coverage-matrix .cell[data-rel="direct"] {
    box-shadow:
        0 0 0 0.125rem var(--surface),
        0 0 0 0.25rem var(--linked-mark, var(--blue-text));
}

.coverage-matrix .cell[data-rel="evidence"] {
    outline: 0.125rem dashed var(--linked-mark, var(--blue-text));
    outline-offset: 0.125rem;
}

.coverage-matrix .cell[data-rel="none"] {
    background: color-mix(in srgb, var(--cell-heat) 25%, var(--surface));
    color: var(--ink-muted);
}

.coverage-matrix tbody tr[data-rel="self"] th,
.coverage-matrix tbody tr[data-rel="direct"] th,
.coverage-matrix tbody tr[data-rel="evidence"] th,
.coverage-matrix thead th[data-rel="self"],
.coverage-matrix thead th[data-rel="direct"],
.coverage-matrix thead th[data-rel="evidence"] {
    background: var(--linked-tint, var(--bg-alt));
    color: var(--ink);
}

.coverage-matrix tbody tr[data-rel="direct"] th .folio span,
.coverage-matrix thead th[data-rel="direct"] .technique,
.coverage-matrix tbody tr[data-rel="evidence"] th .folio span,
.coverage-matrix thead th[data-rel="evidence"] .technique {
    text-decoration: underline 0.125rem var(--linked-mark, var(--blue-text));
    text-underline-offset: 0.25rem;
}

.coverage-matrix tbody tr[data-rel="evidence"] th .folio span,
.coverage-matrix thead th[data-rel="evidence"] .technique {
    text-decoration-style: dashed;
}

.coverage-matrix tbody tr[data-rel="none"] th,
.coverage-matrix thead th[data-rel="none"] {
    color: var(--ink-muted);
}

.coverage-matrix tbody tr[data-preview] th .folio,
.coverage-matrix thead th[data-preview] .technique,
.coverage-matrix .cell[data-preview] {
    outline: 0.125rem dashed var(--linked-mark, var(--blue-text));
    outline-offset: 0.0625rem;
}

.coverage-matrix .none {
    display: grid;
    place-items: center;
    min-block-size: var(--explorer-target, 2.75rem);
    border-radius: 0.25rem;
    background: var(--bg-alt);
    color: var(--ink-muted);
}

.coverage-matrix .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
</style>
