<script setup lang="ts">
import { computed, onBeforeUnmount, useTemplateRef, watch } from "vue";
import { useGettext } from "vue3-gettext";

import LoadingSpinner from "@/manuspectrum/pages/AnalysisExplorer/components/LoadingSpinner.vue";

import { useSeriesSet } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSeriesSet.ts";
import {
    analysisKey,
    fileKey,
} from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
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
const LINE_WIDTH = 2;

/**
 * The quick view of a readable spectrum and of the files of its analysis
 * sharing its axes. Its words are the chart's accessible name; the reset of
 * the zoom is an icon in the chart's corner, shown on hover and on focus.
 */
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
/** A file failed on a server error: Retry may get it. */
const canRetry = computed(() =>
    (results.data.value ?? []).some((result) => result.retryable),
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

/** The file name, followed by the A-label of the file, else of its analysis, when either is in the Selection. */
function legendName(file: FileEntry): string {
    const keys = [
        fileKey(props.analysis.id, file.id),
        analysisKey(props.analysis.id),
    ];
    const slot = keys
        .map((key) => store.basket.find((item) => item.key === key)?.slot)
        .find((found) => found !== undefined);
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
</script>

<template>
    <section
        class="spectrum-preview"
        :aria-busy="results.status.value === 'loading' ? 'true' : 'false'"
    >
        <p
            v-if="results.status.value === 'loading' && !results.data.value"
            class="state loading"
        >
            <LoadingSpinner />
            <span>{{ $gettext("Loading the spectra…") }}</span>
        </p>
        <div
            v-if="curves.length > 0"
            class="plot"
        >
            <div
                ref="chart"
                class="chart"
                role="img"
                :aria-label="summary"
            ></div>
            <button
                type="button"
                class="reset"
                :aria-label="$gettext('Reset the zoom')"
                :title="$gettext('Reset the zoom')"
                @click="reset"
            >
                <svg
                    viewBox="0 0 16 16"
                    aria-hidden="true"
                >
                    <path d="M3 8a5 5 0 1 0 1.5-3.5M3 2.5v2.5h2.5" />
                </svg>
            </button>
        </div>
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
        <button
            v-if="canRetry"
            type="button"
            class="retry"
            @click="results.retry"
        >
            <span>{{ $gettext("Retry") }}</span>
        </button>
    </section>
</template>

<style scoped>
.spectrum-preview {
    display: grid;
    gap: 0.5rem;
}

.spectrum-preview .loading {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
}

.spectrum-preview .plot {
    position: relative;
}

.spectrum-preview .chart {
    min-block-size: 16rem;
}

.spectrum-preview .notes,
.spectrum-preview .state {
    color: var(--ink-muted);
    font-size: 0.875rem;
}

.spectrum-preview .notes {
    padding-inline-start: 1.25rem;
}

.spectrum-preview .reset {
    position: absolute;
    inset-block-start: 0.25rem;
    inset-inline-end: 0.25rem;
    display: grid;
    place-items: center;
    inline-size: 2rem;
    block-size: 2rem;
    padding: 0;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    opacity: 0;
    cursor: pointer;
    transition: opacity 0.15s ease;
}

.spectrum-preview .plot:hover .reset,
.spectrum-preview .reset:focus-visible {
    opacity: 1;
}

.spectrum-preview .reset svg {
    inline-size: 1rem;
    block-size: 1rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
}

.spectrum-preview .retry {
    justify-self: start;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.spectrum-preview button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

@media (hover: none) {
    .spectrum-preview .reset {
        opacity: 1;
    }
}
</style>
