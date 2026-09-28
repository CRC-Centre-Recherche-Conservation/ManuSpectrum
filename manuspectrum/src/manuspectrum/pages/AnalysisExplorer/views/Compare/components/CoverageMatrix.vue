<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import TechniqueCode from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/TechniqueCode.vue";

import type {
    SynthesisCoverage,
    Technique,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * The coverage matrix of the Selection: its canvases in rows, techniques in
 * columns (those the rows shown count), the number of analyses in each cell. A cell with analyses is a
 * toggle button naming its canvas, technique and count; the cell `pressed`
 * names is pressed. An empty cell says it holds no published analysis.
 * The other tools' filters narrow the rows only (`toolView`): a column
 * stays while a row shown counts its technique, even one no kept pair cites.
 */
const props = defineProps<{
    rows: readonly SynthesisCoverage[];
    techniques: readonly Technique[];
    pressed: readonly [string, string] | null;
    /** Marks every toggle `aria-disabled` (a stale matrix while the next one is read). */
    disabled?: boolean;
}>();

const emit = defineEmits<{
    (event: "toggle", payload: { canvas: string; technique: string }): void;
}>();

const { $gettext, $ngettext, interpolate } = useGettext();

const shownTechniques = computed(() =>
    props.techniques.filter((technique) =>
        props.rows.some((row) => countOf(row, technique) > 0),
    ),
);

function countOf(row: SynthesisCoverage, technique: Technique): number {
    return row.counts[technique.id] ?? 0;
}

function isPressed(row: SynthesisCoverage, technique: Technique): boolean {
    return (
        props.pressed !== null &&
        props.pressed[0] === row.canvas &&
        props.pressed[1] === technique.id
    );
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
                    >
                        <span class="technique">
                            <TechniqueCode
                                :code="technique.code"
                                :colour="technique.colour"
                            />
                            <span :lang="technique.label.lang">{{
                                technique.label.value
                            }}</span>
                        </span>
                    </th>
                </tr>
            </thead>
            <tbody>
                <tr
                    v-for="row in props.rows"
                    :key="row.canvas"
                >
                    <th scope="row">
                        <span>{{ row.label }}</span>
                    </th>
                    <td
                        v-for="technique in shownTechniques"
                        :key="technique.id"
                    >
                        <button
                            v-if="countOf(row, technique) > 0"
                            type="button"
                            :aria-label="cellLabel(row, technique)"
                            :aria-pressed="
                                isPressed(row, technique) ? 'true' : 'false'
                            "
                            :aria-disabled="props.disabled ? 'true' : undefined"
                            @click="
                                emit('toggle', {
                                    canvas: row.canvas,
                                    technique: technique.id,
                                })
                            "
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
</template>

<style scoped>
.coverage-matrix {
    overflow-x: auto;
}

.coverage-matrix table {
    border-collapse: collapse;
    font-size: 0.8125rem;
}

.coverage-matrix th,
.coverage-matrix td {
    padding: 0.25rem 0.375rem;
    border-block-end: 0.0625rem solid var(--border);
    text-align: center;
}

.coverage-matrix thead th {
    color: var(--ink-muted);
    font-weight: 600;
    white-space: nowrap;
}

.coverage-matrix thead th:first-child,
.coverage-matrix tbody th {
    text-align: start;
}

.coverage-matrix tbody th {
    font-weight: 600;
    white-space: nowrap;
}

.coverage-matrix .technique {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
}

.coverage-matrix button {
    min-inline-size: var(--explorer-target, 2.75rem);
    min-block-size: var(--explorer-target, 2.75rem);
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: 600 0.8125rem var(--font-mono);
    cursor: pointer;
}

.coverage-matrix button[aria-pressed="true"] {
    border-color: var(--ink);
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

.coverage-matrix .none {
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
