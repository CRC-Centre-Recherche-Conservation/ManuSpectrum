<script setup lang="ts">
import { useGettext } from "vue3-gettext";

import type {
    CurveRow,
    Extent,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";

const SIGNIFICANT_DIGITS = 6;

/**
 * The curves of an XY window as a table, the chart's accessible equivalent:
 * one row per curve with its point count and its X and Y ranges as drawn.
 * Every value of a full series would make a table nobody can read; they are
 * in the CSV. While the linked selection holds something, a row carries how
 * it is linked in `data-rel`, a linked row a bar, a row it does not link
 * muted text.
 */
const props = defineProps<{
    rows: readonly CurveRow[];
    xTitle: string;
    yTitle: string;
}>();

const { $gettext, interpolate } = useGettext();
const numberFormat = new Intl.NumberFormat(
    document.documentElement.lang || "en",
    { maximumSignificantDigits: SIGNIFICANT_DIGITS },
);

function range(span: Extent | null): string {
    if (!span) return "–";
    return interpolate(
        $gettext("%{from} to %{to}"),
        {
            from: numberFormat.format(span.min),
            to: numberFormat.format(span.max),
        },
        true,
    );
}

function titled(axis: string, title: string): string {
    return title ? `${axis} (${title})` : axis;
}
</script>

<template>
    <table class="xy-curve-list">
        <caption>
            <span>{{ $gettext("The curves drawn, one row per curve") }}</span>
        </caption>
        <thead>
            <tr>
                <th scope="col">
                    <span>{{ $gettext("Curve") }}</span>
                </th>
                <th scope="col">
                    <span>{{ $gettext("Analysis") }}</span>
                </th>
                <th scope="col">
                    <span>{{ $gettext("Points") }}</span>
                </th>
                <th scope="col">
                    <span>{{ titled($gettext("X range"), props.xTitle) }}</span>
                </th>
                <th scope="col">
                    <span>{{ titled($gettext("Y range"), props.yTitle) }}</span>
                </th>
            </tr>
        </thead>
        <tbody>
            <tr
                v-for="row in props.rows"
                :key="row.id"
                :data-rel="row.relation"
            >
                <th
                    class="curve"
                    scope="row"
                >
                    <span>{{ row.label }}</span>
                    <span
                        v-if="row.outOfRange"
                        class="flag"
                        >{{ $gettext("out of the shared X range") }}</span
                    >
                </th>
                <td :lang="row.analysis.lang">
                    <span>{{ row.analysis.value }}</span>
                </td>
                <td class="number">
                    <span>{{ numberFormat.format(row.y?.count ?? 0) }}</span>
                </td>
                <td class="number">
                    <span>{{ range(row.x) }}</span>
                </td>
                <td class="number">
                    <span>{{ range(row.y) }}</span>
                </td>
            </tr>
        </tbody>
    </table>
</template>

<style scoped>
.xy-curve-list {
    inline-size: 100%;
    border-collapse: collapse;
    font-size: 0.8125rem;
}

.xy-curve-list caption {
    color: var(--ink-muted);
    text-align: start;
}

.xy-curve-list th,
.xy-curve-list td {
    padding: 0.25rem 0.5rem;
    border-block-end: 0.0625rem solid var(--border-hover);
    text-align: start;
    vertical-align: baseline;
}

.xy-curve-list tr[data-rel="self"] th,
.xy-curve-list tr[data-rel="direct"] th,
.xy-curve-list tr[data-rel="evidence"] th {
    border-inline-start: 0.1875rem solid var(--blue-text);
}

.xy-curve-list tr[data-rel="none"] {
    color: var(--ink-muted);
}

.xy-curve-list .curve {
    font-family: var(--font-mono);
    font-weight: 400;
    overflow-wrap: anywhere;
}

.xy-curve-list .flag {
    display: block;
    color: var(--ink-muted);
    font-family: var(--font-body);
    font-size: 0.75rem;
}

.xy-curve-list .number {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
}
</style>
