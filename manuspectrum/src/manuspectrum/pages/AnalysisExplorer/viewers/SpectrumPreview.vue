<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useTemplateRef, watch } from "vue";
import { useGettext } from "vue3-gettext";

import Column from "primevue/column";
import DataTable from "primevue/datatable";

import { useSeriesSet } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSeriesSet.ts";
import { fileKey } from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { loadPlotly } from "@/manuspectrum/pages/AnalysisExplorer/xy/plotly.ts";
import {
    PLOT_CONFIG,
    plotLayout,
    readPlotTheme,
    resetAxes,
    seriesColour,
    whenFontsReady,
} from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

import type {
    AnalysisPayload,
    FileEntry,
    Series,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

type PlotlyModule = Awaited<ReturnType<typeof loadPlotly>>;

interface Curve {
    file: FileEntry;
    index: number;
    series: Series;
}

const SIGNIFICANT_DIGITS = 6;
const TABLE_ROW_HEIGHT = 28;
const TABLE_HEIGHT = "20rem";
const LINE_WIDTH = 2;

const props = defineProps<{ file: FileEntry; analysis: AnalysisPayload }>();

const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const results = useSeriesSet(() =>
    drawnFiles().map((entry) => entry.previewUrl ?? ""),
);
const chart = useTemplateRef<HTMLDivElement>("chart");
const lang = document.documentElement.lang || "en";
const numberFormat = new Intl.NumberFormat(lang, {
    maximumSignificantDigits: SIGNIFICANT_DIGITS,
});

const showTable = ref(false);
const tableFile = ref<string | null>(null);
// The Plotly module lives outside Vue reactivity.
let plotly: PlotlyModule | null = null;

const files = computed(() => drawnFiles());
const curves = computed<Curve[]>(() =>
    (results.data.value ?? []).flatMap((result, index) => {
        const file = files.value[index];
        return result.series && file
            ? [{ file, index, series: result.series }]
            : [];
    }),
);
const xReversed = computed(() => curves.value[0]?.series.x_reversed ?? false);
const notes = computed(() =>
    (results.data.value ?? []).flatMap((result, index) => {
        const file = files.value[index];
        if (!file) return [];
        if (result.failed) {
            return [
                interpolate(
                    $gettext("%{name} could not be drawn."),
                    { name: file.name },
                    true,
                ),
            ];
        }
        if (!result.series) {
            return [
                interpolate(
                    $gettext("%{name}: nothing to draw."),
                    { name: file.name },
                    true,
                ),
            ];
        }
        if (result.series.decimated) {
            return [
                interpolate(
                    $gettext(
                        "%{name}: quick view drawn from %{shown} of the file's %{total} points; the workshop works on every point.",
                    ),
                    {
                        name: file.name,
                        shown: result.series.x.length,
                        total: result.series.n_source,
                    },
                    true,
                ),
            ];
        }
        return [];
    }),
);
const summary = computed(() =>
    curves.value
        .map(({ file, series }) =>
            interpolate(
                $gettext("%{name}: %{n} points from %{from} to %{to}."),
                {
                    name: file.name,
                    n: series.x.length,
                    from: numberFormat.format(Math.min(...series.x)),
                    to: numberFormat.format(Math.max(...series.x)),
                },
                true,
            ),
        )
        .join(" "),
);
const tableCurve = computed(
    () =>
        curves.value.find((curve) => curve.file.id === tableFile.value) ??
        curves.value[0] ??
        null,
);
const tableFileId = computed({
    get: () => tableCurve.value?.file.id ?? null,
    set: (id: string | null) => {
        tableFile.value = id;
    },
});
const tableRows = computed(() => {
    const curve = tableCurve.value;
    if (!curve) return [];
    return curve.series.x.map((x, index) => ({
        x: numberFormat.format(x),
        y: numberFormat.format(curve.series.y[index]),
    }));
});
// The preset axis names are English whatever the page language.
const xHeader = computed(() => props.file.viewer.xLabel || "x");
const yHeader = computed(() => props.file.viewer.yLabel || "y");

watch([curves, chart, () => store.basket], () => void draw());

onBeforeUnmount(() => {
    if (plotly && chart.value) plotly.purge(chart.value);
});

/**
 * The readable spectra of the analysis drawn on the same axes as `file`, in
 * the analysis's order; a file without an axis key is drawn alone.
 */
function drawnFiles(): FileEntry[] {
    const axes = props.file.viewer.axisKey;
    return props.analysis.files.filter(
        (entry) =>
            entry.role === "readable" &&
            entry.dataKind === "xy" &&
            entry.previewUrl !== null &&
            (axes === null
                ? entry.id === props.file.id
                : entry.viewer.axisKey === axes),
    );
}

/** The file name, followed by its A-label when the file is in the Selection. */
function legendName(file: FileEntry): string {
    const key = fileKey(props.analysis.id, file.id);
    const slot = store.basket.find((item) => item.key === key)?.slot;
    return slot === undefined ? file.name : `${file.name} (${slotLabel(slot)})`;
}

async function draw(): Promise<void> {
    const element = chart.value;
    if (!element || curves.value.length === 0) return;
    try {
        plotly ??= await loadPlotly();
        await whenFontsReady();
        const theme = readPlotTheme();
        await plotly.react(
            element,
            curves.value.map(({ file, index, series }) => ({
                x: series.x,
                y: series.y,
                name: legendName(file),
                type: "scatter",
                mode: "lines",
                line: { color: seriesColour(theme, index), width: LINE_WIDTH },
            })),
            plotLayout(theme, {
                lang,
                xTitle: props.file.viewer.xLabel ?? "",
                yTitle: props.file.viewer.yLabel ?? "",
                xReversed: xReversed.value,
                legend: curves.value.length > 1,
            }),
            PLOT_CONFIG,
        );
    } catch (error: unknown) {
        console.error("Spectrum quick view could not be drawn", error);
    }
}

async function reset(): Promise<void> {
    if (plotly && chart.value) {
        await resetAxes(plotly, chart.value, xReversed.value);
    }
}

function toggleTable(): void {
    showTable.value = !showTable.value;
}
</script>

<template>
    <section
        class="spectrum-preview"
        :aria-busy="results.status.value === 'loading' ? 'true' : 'false'"
    >
        <p
            v-if="results.status.value === 'loading' && !results.data.value"
            class="state"
        >
            <span>{{ $gettext("Loading the spectra…") }}</span>
        </p>
        <template v-if="curves.length > 0">
            <div class="toolbar">
                <button
                    class="reset"
                    type="button"
                    @click="reset"
                >
                    <span>{{ $gettext("Reset") }}</span>
                </button>
                <button
                    class="table-toggle"
                    type="button"
                    :aria-pressed="showTable ? 'true' : 'false'"
                    @click="toggleTable"
                >
                    <span>{{ $gettext("Table") }}</span>
                </button>
            </div>
            <div
                ref="chart"
                class="chart"
                role="img"
                :aria-label="summary"
            ></div>
            <p class="summary">
                <span>{{ summary }}</span>
            </p>
        </template>
        <ul
            v-if="notes.length > 0"
            class="notes"
        >
            <li
                v-for="(note, index) in notes"
                :key="index"
            >
                <span>{{ note }}</span>
            </li>
        </ul>
        <template v-if="showTable && tableCurve">
            <label
                v-if="curves.length > 1"
                class="table-pick"
            >
                <span>{{ $gettext("File") }}</span>
                <select
                    v-model="tableFileId"
                    class="table-file"
                >
                    <option
                        v-for="curve in curves"
                        :key="curve.file.id"
                        :value="curve.file.id"
                    >
                        {{ curve.file.name }}
                    </option>
                </select>
            </label>
            <DataTable
                class="points"
                size="small"
                :value="tableRows"
                :scrollable="true"
                :scroll-height="TABLE_HEIGHT"
                :virtual-scroller-options="{ itemSize: TABLE_ROW_HEIGHT }"
            >
                <Column field="x">
                    <template #header>
                        <span
                            :lang="props.file.viewer.xLabel ? 'en' : undefined"
                        >
                            {{ xHeader }}
                        </span>
                    </template>
                </Column>
                <Column field="y">
                    <template #header>
                        <span
                            :lang="props.file.viewer.yLabel ? 'en' : undefined"
                        >
                            {{ yHeader }}
                        </span>
                    </template>
                </Column>
            </DataTable>
        </template>
    </section>
</template>

<style scoped>
.spectrum-preview {
    display: grid;
    gap: 0.5rem;
}

.spectrum-preview .chart {
    min-block-size: 16rem;
}

.spectrum-preview .summary,
.spectrum-preview .notes,
.spectrum-preview .state {
    color: var(--ink-muted);
    font-size: 0.875rem;
}

.spectrum-preview .notes {
    padding-inline-start: 1.25rem;
}

.spectrum-preview .toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
}

.spectrum-preview button,
.spectrum-preview select {
    min-block-size: 2.75rem;
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
}

.spectrum-preview button {
    cursor: pointer;
}

.spectrum-preview button:focus-visible,
.spectrum-preview select:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.spectrum-preview .table-pick {
    display: flex;
    gap: 0.5rem;
    align-items: center;
}

.spectrum-preview .points {
    font-family: var(--font-mono);
    font-size: 0.75rem;
}
</style>
