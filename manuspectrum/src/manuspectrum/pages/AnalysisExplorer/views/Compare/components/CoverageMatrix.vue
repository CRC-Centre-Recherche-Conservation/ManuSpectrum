<script setup lang="ts">
import { computed, inject } from "vue";
import { useGettext } from "vue3-gettext";

import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";
import HeatLegend from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/HeatLegend.vue";
import TechniqueCode from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/TechniqueCode.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { FOLIO_REQUEST_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { heatLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/heat.ts";
import {
    canvasNode,
    cellNode,
    componentNode,
    techniqueNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { coverageRows } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";

import type {
    SynthesisCoverage,
    Technique,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { CoverageRow } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";

/**
 * The coverage matrix of the Selection: « folio › component » in rows
 * (`coverageRows`: each canvas split by the component its analyses
 * observe, the folio alone for those observing none), techniques in
 * columns (those the rows shown count, headed by their code, the full name
 * read and shown on hover), the number of analyses in each cell, shaded on
 * the heat ramp (`heatLevel`, the legend under the table says what the
 * number counts). A cell with analyses is a toggle button naming its
 * folio, component, technique and count (`cell:`); a row's folio (`cv:`),
 * its component (`comp:`) and a column's technique (`tech:`) are toggles
 * too. A click adds the node to the linked selection of Compare or
 * removes it; a toggle is pressed while its node is selected. A row's
 * folio or a cell clicked also asks the folio image tools to show that
 * folio (`FOLIO_REQUEST_KEY`). Every toggle carries the focus marks
 * (`useLinkedMarks().focus`, the `ms-focus` ring, pip and bloom); rows and
 * column headers are marked by how their folio, component and technique
 * stand to the focus and to the node a mouse previews; an unlinked cell
 * keeps a part of its shade. An empty cell says it holds no published
 * analysis.
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

const matrixRows = computed(() => coverageRows(props.rows));

const shownTechniques = computed(() =>
    props.techniques.filter((technique) =>
        matrixRows.value.some((row) => countOf(row, technique) > 0),
    ),
);

const maxCount = computed(() =>
    Math.max(
        0,
        ...matrixRows.value.flatMap((row) =>
            shownTechniques.value.map((technique) => countOf(row, technique)),
        ),
    ),
);

function countOf(row: CoverageRow, technique: Technique): number {
    return row.counts[technique.id] ?? 0;
}

function rowKey(row: CoverageRow): string {
    return `${row.canvas}|${row.component?.id ?? ""}`;
}

/** The nodes a row stands for: its folio, and its component when it has one. */
function rowNodes(row: CoverageRow): NodeId[] {
    return row.component
        ? [canvasNode(row.canvas), componentNode(row.component.id)]
        : [canvasNode(row.canvas)];
}

function cellOf(row: CoverageRow, technique: Technique): NodeId {
    return cellNode(row.canvas, row.component?.id ?? null, technique.id);
}

function toggle(node: NodeId): void {
    if (!props.disabled) marks.toggle(node);
}

/** Toggles `node` and shows the folio of `row` in the folio image tools. */
function toggleOnFolio(node: NodeId, row: CoverageRow): void {
    if (props.disabled) return;
    marks.toggle(node);
    folios?.show(row.canvas, row.label);
}

function cellLabel(row: CoverageRow, technique: Technique): string {
    const count = countOf(row, technique);
    if (!row.component) {
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
    return interpolate(
        $ngettext(
            "%{canvas}, %{component}, %{technique}: %{n} analysis",
            "%{canvas}, %{component}, %{technique}: %{n} analyses",
            count,
        ),
        {
            canvas: row.label,
            component: row.component.name.value,
            technique: technique.label.value,
            n: count,
        },
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
                            <span>{{ $gettext("Folio › component") }}</span>
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
                                class="technique ms-focus"
                                v-bind="
                                    marks.focus(techniqueNode(technique.id))
                                "
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
                                <FocusPip :node="techniqueNode(technique.id)" />
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
                        v-for="row in matrixRows"
                        :key="rowKey(row)"
                        :data-rel="marks.rel(rowNodes(row))"
                        :data-preview="marks.previewRel(rowNodes(row))"
                    >
                        <th scope="row">
                            <span class="row-head">
                                <button
                                    type="button"
                                    class="folio ms-focus"
                                    v-bind="marks.focus(canvasNode(row.canvas))"
                                    :aria-pressed="
                                        marks.pressed(canvasNode(row.canvas))
                                    "
                                    :aria-disabled="
                                        props.disabled ? 'true' : undefined
                                    "
                                    @click="
                                        toggleOnFolio(
                                            canvasNode(row.canvas),
                                            row,
                                        )
                                    "
                                    @pointerenter="
                                        marks.enter(
                                            canvasNode(row.canvas),
                                            $event,
                                        )
                                    "
                                    @pointerleave="marks.leave($event)"
                                >
                                    <FocusPip :node="canvasNode(row.canvas)" />
                                    <span>{{ row.label }}</span>
                                </button>
                                <template v-if="row.component">
                                    <span
                                        class="separator"
                                        aria-hidden="true"
                                        >›</span
                                    >
                                    <button
                                        type="button"
                                        class="component ms-focus"
                                        v-bind="
                                            marks.focus(
                                                componentNode(row.component.id),
                                            )
                                        "
                                        :lang="row.component.name.lang"
                                        :aria-pressed="
                                            marks.pressed(
                                                componentNode(row.component.id),
                                            )
                                        "
                                        :aria-disabled="
                                            props.disabled ? 'true' : undefined
                                        "
                                        @click="
                                            toggle(
                                                componentNode(row.component.id),
                                            )
                                        "
                                        @pointerenter="
                                            marks.enter(
                                                componentNode(row.component.id),
                                                $event,
                                            )
                                        "
                                        @pointerleave="marks.leave($event)"
                                    >
                                        <FocusPip
                                            :node="
                                                componentNode(row.component.id)
                                            "
                                        />
                                        <span
                                            class="glyph"
                                            aria-hidden="true"
                                        ></span>
                                        <span>{{
                                            row.component.name.value
                                        }}</span>
                                    </button>
                                </template>
                            </span>
                        </th>
                        <td
                            v-for="technique in shownTechniques"
                            :key="technique.id"
                        >
                            <button
                                v-if="countOf(row, technique) > 0"
                                type="button"
                                class="cell ms-focus"
                                v-bind="marks.focus(cellOf(row, technique))"
                                :data-heat="
                                    heatLevel(countOf(row, technique), maxCount)
                                "
                                :aria-label="cellLabel(row, technique)"
                                :aria-pressed="
                                    marks.pressed(cellOf(row, technique))
                                "
                                :aria-disabled="
                                    props.disabled ? 'true' : undefined
                                "
                                @click="
                                    toggleOnFolio(cellOf(row, technique), row)
                                "
                                @pointerenter="
                                    marks.enter(cellOf(row, technique), $event)
                                "
                                @pointerleave="marks.leave($event)"
                            >
                                <FocusPip :node="cellOf(row, technique)" />
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
                    'Analyses of the Selection on the folio and component with the technique',
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
    padding-block-start: 0.5rem;
    padding-inline-end: 0.5rem;
    overflow-x: auto;
}

.coverage-matrix table {
    inline-size: 100%;
    border-collapse: separate;
    border-spacing: 0.3125rem var(--focus-room);
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
    transition: color var(--dur-med, 260ms);
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

.coverage-matrix .row-head {
    display: inline-flex;
    align-items: center;
    gap: 0.125rem;
}

.coverage-matrix .separator {
    color: var(--ink-dim);
}

.coverage-matrix .technique,
.coverage-matrix .folio,
.coverage-matrix .component {
    --r: 0.375rem;
    --link-pip: 0.8125rem;
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.375rem;
    border: 0.0625rem solid transparent;
    border-radius: 0.375rem;
    background: none;
    color: inherit;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
}

.coverage-matrix .technique:hover,
.coverage-matrix .folio:hover,
.coverage-matrix .component:hover {
    border-color: var(--border-hover);
}

.coverage-matrix .component {
    font-family: var(--font-body);
    font-size: 0.75rem;
    font-weight: 400;
}

.coverage-matrix .component .glyph {
    flex: none;
    inline-size: 0.75rem;
    block-size: 0.75rem;
    border: 0.09375rem dashed var(--ink-dim);
    border-radius: 0.1875rem;
}

.coverage-matrix .cell {
    --cell-heat: var(--heat-1);
    --cell-on: var(--heat-1-on);
    --r: 0.375rem;

    inline-size: 100%;
    min-inline-size: var(--explorer-target, 2.75rem);
    min-block-size: var(--explorer-target, 2.75rem);
    border: none;
    border-radius: 0.375rem;
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

.coverage-matrix button[aria-disabled="true"] {
    cursor: default;
}

.coverage-matrix button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.1875rem;
}

.coverage-matrix
    tbody
    tr:is([data-rel="self"], [data-rel="direct"], [data-rel="evidence"])
    th,
.coverage-matrix
    thead
    th:is([data-rel="self"], [data-rel="direct"], [data-rel="evidence"]) {
    color: var(--ink);
}

.coverage-matrix tbody tr[data-rel="none"] th,
.coverage-matrix thead th[data-rel="none"] {
    color: var(--ink-muted);
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
