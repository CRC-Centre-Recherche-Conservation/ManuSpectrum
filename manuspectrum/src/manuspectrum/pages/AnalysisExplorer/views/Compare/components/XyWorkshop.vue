<script setup lang="ts">
import {
    computed,
    inject,
    onBeforeUnmount,
    ref,
    useId,
    useTemplateRef,
    watch,
} from "vue";
import { useGettext } from "vue3-gettext";
import { deriveAxisLabel } from "utils/xy-transforms";
import { BASE_VIEW } from "utils/xy-views";

import LoadingSpinner from "@/manuspectrum/pages/AnalysisExplorer/components/LoadingSpinner.vue";
import XyCurveList from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/XyCurveList.vue";

import { useSeriesSet } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSeriesSet.ts";
import { WINDOW_RESIZE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    annotationLabels,
    viewLabels,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/treatment-labels.ts";
import {
    OVERLAY_MAX_CURVES,
    dashOf,
    extent,
    offsetLifts,
    outOfRange,
    panelGrid,
    ranksInSlot,
    sharedViews,
    treat,
    workshopCsv,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";
import { firstStoredTitle } from "@/manuspectrum/pages/AnalysisExplorer/xy/axis-titles.ts";
import { loadPlotly } from "@/manuspectrum/pages/AnalysisExplorer/xy/plotly.ts";
import {
    PLOT_CONFIG,
    plotLayout,
    readPlotTheme,
    resetAxes,
    seriesColour,
    whenFontsReady,
} from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

import type { Layout, PlotData } from "plotly.js";
import type { XyView } from "utils/xy-views";
import type { SeriesResult } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSeriesSet.ts";
import type { FileLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";
import type {
    CurveRow,
    Extent,
    WorkshopLayout,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";
import type { PlotTheme } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

type PlotlyModule = Awaited<ReturnType<typeof loadPlotly>>;

interface Figure {
    data: Partial<PlotData>[];
    layout: Partial<Layout>;
}

interface Curve {
    line: FileLine;
    label: string;
    rank: number;
    x: number[];
    /** The values drawn: the series after the treatment, before any offset. */
    y: number[];
    xRange: Extent | null;
    yRange: Extent | null;
    xReversed: boolean;
}

const LINE_WIDTH = 2;
const PANEL_MARGIN_TOP = 28;
const LABEL_FONT_SIZE = 11;
const PNG_FILE = "spectra.png";
const CSV_FILE = "spectra.csv";
const DEFAULT_PNG_WIDTH = 960;
const DEFAULT_PNG_HEIGHT = 540;

/**
 * The XY workshop of a Compare window (§10, D51, D61, D62): every point of
 * every readable spectrum of the window, each in the colour of its slot,
 * the 2nd, 3rd… file of a slot in a dashed variant, named « A1 · file ».
 * Overlaid, offset (each curve lifted above the one before it, the real
 * values on hover, the Y title unchanged), in small multiples (one panel
 * per slot, the default above eight curves) or as a table. A treatment of
 * `utils/xy-views.js` runs on every curve and names itself in the Y title.
 * A file over the server's ceiling, missing or empty is named and left out.
 * A chart Plotly cannot draw says so in the window. The chart follows its
 * window's size (`WINDOW_RESIZE_KEY`) only when its own size changed; the
 * table layout and the unmount purge it, and a drawing that ends after the
 * unmount is purged too.
 */
const props = defineProps<{ curves: readonly FileLine[] }>();

const resizeTick = inject(WINDOW_RESIZE_KEY, null);

const { $gettext, $ngettext, interpolate } = useGettext();
const readable = computed(() =>
    props.curves.filter((curve) => curve.file.previewUrl !== null),
);
const results = useSeriesSet(
    () => readable.value.map((curve) => curve.file.previewUrl ?? ""),
    "full",
);
const chart = useTemplateRef<HTMLDivElement>("chart");
const csvNoteId = useId();
const lang = document.documentElement.lang || "en";

// The Plotly module and the element it drew in live outside Vue reactivity.
let plotly: PlotlyModule | null = null;
let drawnOn: HTMLElement | null = null;
let lastFigure: Figure | null = null;
/** The chart's size when it was last drawn or resized, « width×height ». */
let drawnSize = "";
/** Set on unmount: a drawing still waiting stops, and one that ends late is purged. */
let disposed = false;

/** The layout the reader picked; null follows the number of curves. */
const chosenLayout = ref<WorkshopLayout | null>(null);
const viewKey = ref<string>(BASE_VIEW);
/** Plotly could not be loaded or could not draw the last figure. */
const drawFailed = ref(false);

/** Each readable file's answer, by preview URL, once the answer is for the files shown. */
const answers = computed(() => {
    const urls = results.loaded.value?.split("\n") ?? [];
    const data = results.data.value ?? [];
    return new Map<string, SeriesResult>(
        urls.map((url, index) => [url, data[index]]),
    );
});
const loadedCurves = computed(() =>
    readable.value.flatMap((line) => {
        const series = answers.value.get(line.file.previewUrl ?? "")?.series;
        return series ? [{ line, series }] : [];
    }),
);
const treatments = computed(() =>
    sharedViews(
        loadedCurves.value.map(({ line }) => line.file.viewer.presetKey),
    ),
);
const view = computed<XyView>(
    () =>
        treatments.value.views.find((entry) => entry.key === viewKey.value) ??
        treatments.value.views[0],
);
const viewNames = computed(() => viewLabels($gettext));
const drawn = computed<Curve[]>(() => {
    const ranks = ranksInSlot(loadedCurves.value.map(({ line }) => line.slot));
    return loadedCurves.value.map(({ line, series }, index) => {
        const y = treat(series.x, series.y, view.value);
        return {
            line,
            label: `${slotLabel(line.slot)} · ${line.file.name}`,
            rank: ranks[index],
            x: series.x,
            y,
            xRange: extent(series.x),
            yRange: extent(y),
            xReversed: series.x_reversed,
        };
    });
});
const slots = computed(() => [
    ...new Set(drawn.value.map((curve) => curve.line.slot)),
]);
const layouts = computed<WorkshopLayout[]>(() =>
    slots.value.length > 1
        ? ["overlay", "offset", "multiples", "table"]
        : ["overlay", "offset", "table"],
);
const layout = computed<WorkshopLayout>(() => {
    const wanted =
        chosenLayout.value ??
        (drawn.value.length > OVERLAY_MAX_CURVES ? "multiples" : "overlay");
    return layouts.value.includes(wanted) ? wanted : "overlay";
});
const xReversed = computed(() => drawn.value[0]?.xReversed ?? false);
/** The first stored title among the spectra drawn; a treatment qualifies the Y title. */
const titles = computed(() => {
    const viewers = drawn.value.map((curve) => curve.line.file.viewer);
    const x = firstStoredTitle(viewers.map((viewer) => viewer.xLabel)) ?? "";
    const y = firstStoredTitle(viewers.map((viewer) => viewer.yLabel)) ?? "";
    return {
        x,
        y: deriveAxisLabel(
            y,
            { transforms: view.value.transforms },
            annotationLabels($gettext),
        ),
    };
});
const flags = computed(() =>
    outOfRange(drawn.value.map((curve) => curve.xRange)),
);
const rows = computed<CurveRow[]>(() =>
    drawn.value.map((curve, index) => ({
        id: `${curve.line.key}|${curve.line.file.id}`,
        label: curve.label,
        analysis: curve.line.analysis.name,
        x: curve.xRange,
        y: curve.yRange,
        outOfRange: flags.value[index],
    })),
);
const notes = computed(() => {
    const found: string[] = [];
    for (const line of props.curves) {
        const name = `${slotLabel(line.slot)} · ${line.file.name}`;
        const answer = line.file.previewUrl
            ? answers.value.get(line.file.previewUrl)
            : { series: null, failed: false, tooLarge: false };
        if (!answer) continue;
        if (answer.tooLarge) {
            found.push(
                interpolate(
                    $gettext(
                        "%{name}: too large to draw in full; download the file to read it.",
                    ),
                    { name },
                    true,
                ),
            );
        } else if (answer.failed) {
            found.push(
                interpolate(
                    $gettext("%{name} could not be drawn."),
                    { name },
                    true,
                ),
            );
        } else if (!answer.series) {
            found.push(
                interpolate(
                    $gettext("%{name}: nothing to draw."),
                    { name },
                    true,
                ),
            );
        }
    }
    drawn.value.forEach((curve, index) => {
        if (flags.value[index]) {
            found.push(
                interpolate(
                    $gettext("%{name}: out of the shared X range."),
                    { name: curve.label },
                    true,
                ),
            );
        }
    });
    return found;
});
const canRetry = computed(() =>
    (results.data.value ?? []).some((result) => result.retryable),
);
const loading = computed(
    () => results.status.value === "loading" && drawn.value.length === 0,
);
const chartLabel = computed(() =>
    interpolate(
        $ngettext(
            "Chart of %{n} spectrum; the Table layout lists its range.",
            "Chart of %{n} spectra; the Table layout lists their ranges.",
            drawn.value.length,
        ),
        { n: drawn.value.length },
        true,
    ),
);

watch([drawn, layout, chart], () => void draw());
watch(layout, (name) => {
    if (name === "table") purgeChart();
});
watch(
    () => resizeTick?.value,
    () => {
        const element = chart.value;
        if (!plotly || !element || layout.value === "table") return;
        const size = sizeOf(element);
        if (size === drawnSize) return;
        drawnSize = size;
        void plotly.Plots.resize(element);
    },
);

onBeforeUnmount(() => {
    disposed = true;
    purgeChart();
});

function sizeOf(element: HTMLElement): string {
    return `${element.clientWidth}×${element.clientHeight}`;
}

/** Frees the chart Plotly drew, and forgets it. */
function purgeChart(): void {
    if (plotly && drawnOn) plotly.purge(drawnOn);
    drawnOn = null;
    lastFigure = null;
}

function layoutName(name: WorkshopLayout): string {
    switch (name) {
        case "overlay":
            return $gettext("Overlay");
        case "offset":
            return $gettext("Offset");
        case "multiples":
            return $gettext("Small multiples");
        default:
            return $gettext("Table");
    }
}

function viewName(entry: XyView): string {
    return viewNames.value[entry.key] ?? entry.key;
}

function lineOf(theme: PlotTheme, curve: Curve): Partial<PlotData>["line"] {
    return {
        color: seriesColour(theme, curve.line.slot),
        width: LINE_WIDTH,
        dash: dashOf(curve.rank),
    };
}

/** The last finite point of a curve, where a curve past the series colours (A9…A30, in ink) carries its label. */
function lastPoint(x: number[], y: number[]): [number, number] | null {
    for (let index = y.length - 1; index >= 0; index -= 1) {
        if (Number.isFinite(x[index]) && Number.isFinite(y[index])) {
            return [x[index], y[index]];
        }
    }
    return null;
}

function inkLabel(
    theme: PlotTheme,
    curve: Curve,
    y: number[],
): Partial<Layout["annotations"][number]>[] {
    if (curve.line.slot < theme.series.length) return [];
    const point = lastPoint(curve.x, y);
    if (!point) return [];
    return [
        {
            x: point[0],
            y: point[1],
            text: slotLabel(curve.line.slot),
            showarrow: false,
            xanchor: "left",
            font: {
                family: theme.fontMono,
                size: LABEL_FONT_SIZE,
                color: theme.ink,
            },
        },
    ];
}

function baseLayout(theme: PlotTheme): Partial<Layout> {
    return plotLayout(theme, {
        lang,
        xTitle: titles.value.x,
        yTitle: titles.value.y,
        xReversed: xReversed.value,
        legend: drawn.value.length > 1,
    });
}

/** Overlaid, or offset: each curve lifted above the one before it, its real values kept for the hover. */
function stackedFigure(theme: PlotTheme, offset: boolean): Figure {
    const lifts = offset
        ? offsetLifts(drawn.value.map((curve) => curve.yRange))
        : [];
    const annotations: Partial<Layout["annotations"][number]>[] = [];
    const data = drawn.value.map((curve, index): Partial<PlotData> => {
        const lift = lifts[index] ?? 0;
        const y = offset ? curve.y.map((value) => value + lift) : curve.y;
        annotations.push(...inkLabel(theme, curve, y));
        return {
            x: curve.x,
            y,
            name: curve.label,
            type: "scatter",
            mode: "lines",
            line: lineOf(theme, curve),
            ...(offset
                ? { customdata: curve.y, hovertemplate: "%{customdata:.6~g}" }
                : {}),
        };
    });
    return { data, layout: { ...baseLayout(theme), annotations } };
}

/** One panel per slot, each with its own axes and its slot label. */
function multiplesFigure(theme: PlotTheme): Figure {
    const base = baseLayout(theme);
    const panels = slots.value.length;
    const { rows, columns } = panelGrid(panels);
    const layout: Record<string, unknown> = {
        ...base,
        grid: { rows, columns, pattern: "independent" },
        margin: { ...base.margin, t: PANEL_MARGIN_TOP },
    };
    const annotations: Partial<Layout["annotations"][number]>[] = [];
    slots.value.forEach((slot, panel) => {
        const suffix = panel === 0 ? "" : String(panel + 1);
        const bottom = panel + columns >= panels;
        const first = panel % columns === 0;
        layout[`xaxis${suffix}`] = {
            ...base.xaxis,
            title: { ...base.xaxis?.title, text: bottom ? titles.value.x : "" },
        };
        layout[`yaxis${suffix}`] = {
            ...base.yaxis,
            title: { ...base.yaxis?.title, text: first ? titles.value.y : "" },
        };
        annotations.push({
            xref: `x${suffix} domain` as Layout["annotations"][number]["xref"],
            yref: `y${suffix} domain` as Layout["annotations"][number]["yref"],
            x: 0,
            y: 1,
            xanchor: "left",
            yanchor: "bottom",
            showarrow: false,
            text: slotLabel(slot),
            font: {
                family: theme.fontMono,
                size: LABEL_FONT_SIZE,
                color: seriesColour(theme, slot),
            },
        });
    });
    const data = drawn.value.map((curve): Partial<PlotData> => {
        const panel = slots.value.indexOf(curve.line.slot);
        const suffix = panel === 0 ? "" : String(panel + 1);
        return {
            x: curve.x,
            y: curve.y,
            name: curve.label,
            type: "scatter",
            mode: "lines",
            line: lineOf(theme, curve),
            xaxis: `x${suffix}`,
            yaxis: `y${suffix}`,
        };
    });
    return {
        data,
        layout: { ...layout, annotations } as Partial<Layout>,
    };
}

async function draw(): Promise<void> {
    const element = chart.value;
    if (!element || drawn.value.length === 0 || layout.value === "table") {
        return;
    }
    try {
        plotly ??= await loadPlotly();
        if (disposed) return;
        await whenFontsReady();
        if (disposed) return;
        if (drawnOn && drawnOn !== element) plotly.purge(drawnOn);
        const theme = readPlotTheme();
        const figure =
            layout.value === "multiples"
                ? multiplesFigure(theme)
                : stackedFigure(theme, layout.value === "offset");
        lastFigure = figure;
        drawnOn = element;
        drawnSize = sizeOf(element);
        await plotly.react(element, figure.data, figure.layout, PLOT_CONFIG);
        if (disposed) {
            plotly.purge(element);
            return;
        }
        drawFailed.value = false;
    } catch (error: unknown) {
        if (disposed) return;
        drawFailed.value = true;
        console.error("Spectra comparison could not be drawn", error);
    }
}

async function reset(): Promise<void> {
    if (plotly && chart.value) {
        await resetAxes(
            plotly,
            chart.value,
            xReversed.value,
            layout.value === "multiples" ? slots.value.length : 1,
        );
    }
}

function save(href: string, name: string): void {
    const link = document.createElement("a");
    link.href = href;
    link.download = name;
    link.click();
}

/** The chart as a PNG, on the page's background rather than the transparent one of the screen. */
async function downloadPng(): Promise<void> {
    const element = chart.value;
    if (!plotly || !element || !lastFigure) return;
    const { background } = readPlotTheme();
    try {
        const url = await plotly.toImage(
            {
                data: lastFigure.data,
                layout: {
                    ...lastFigure.layout,
                    paper_bgcolor: background,
                    plot_bgcolor: background,
                },
            },
            {
                format: "png",
                width: element.clientWidth || DEFAULT_PNG_WIDTH,
                height: element.clientHeight || DEFAULT_PNG_HEIGHT,
            },
        );
        save(url, PNG_FILE);
    } catch (error: unknown) {
        console.error("Spectra comparison could not be exported", error);
    }
}

/** The values drawn, treatment included and offset left out. */
function downloadCsv(): void {
    const text = workshopCsv(
        drawn.value.map((curve) => ({
            label: curve.label,
            x: curve.x,
            y: curve.y,
        })),
        titles.value.x || "X",
        titles.value.y || "Y",
    );
    const url = URL.createObjectURL(
        new Blob([text], { type: "text/csv;charset=utf-8" }),
    );
    save(url, CSV_FILE);
    setTimeout(() => URL.revokeObjectURL(url), 0);
}

function chooseLayout(name: WorkshopLayout): void {
    chosenLayout.value = name;
}

function chooseView(event: Event): void {
    viewKey.value = (event.target as HTMLSelectElement).value;
}
</script>

<template>
    <section
        class="xy-workshop"
        :aria-busy="results.status.value === 'loading' ? 'true' : 'false'"
    >
        <p
            v-if="loading"
            class="state"
        >
            <LoadingSpinner />
            <span>{{ $gettext("Loading the spectra…") }}</span>
        </p>
        <template v-if="drawn.length > 0">
            <div
                class="toolbar"
                role="group"
                :aria-label="$gettext('Chart tools')"
            >
                <div
                    class="layouts"
                    role="group"
                    :aria-label="$gettext('Layout')"
                >
                    <button
                        v-for="name in layouts"
                        :key="name"
                        type="button"
                        :data-layout="name"
                        :aria-pressed="layout === name ? 'true' : 'false'"
                        @click="chooseLayout(name)"
                    >
                        <span>{{ layoutName(name) }}</span>
                    </button>
                </div>
                <label
                    v-if="treatments.views.length > 1"
                    class="treatment"
                >
                    <span>{{ $gettext("Treatment") }}</span>
                    <select
                        :value="view.key"
                        @change="chooseView"
                    >
                        <option
                            v-for="entry in treatments.views"
                            :key="entry.key"
                            :value="entry.key"
                        >
                            {{ viewName(entry) }}
                        </option>
                    </select>
                </label>
                <button
                    v-if="layout !== 'table'"
                    type="button"
                    data-action="reset"
                    @click="reset"
                >
                    <span>{{ $gettext("Reset the zoom") }}</span>
                </button>
                <button
                    v-if="layout !== 'table'"
                    type="button"
                    data-action="png"
                    @click="downloadPng"
                >
                    <span>{{ $gettext("Download PNG") }}</span>
                </button>
                <button
                    type="button"
                    data-action="csv"
                    :aria-describedby="csvNoteId"
                    @click="downloadCsv"
                >
                    <span>{{ $gettext("Download CSV") }}</span>
                </button>
            </div>
            <p
                v-if="treatments.mixed"
                class="note mixed"
            >
                <span>{{
                    $gettext(
                        "These spectra come from different configurations: only the treatments they share are offered.",
                    )
                }}</span>
            </p>
            <XyCurveList
                v-if="layout === 'table'"
                :rows="rows"
                :x-title="titles.x"
                :y-title="titles.y"
            />
            <p
                v-if="drawFailed && layout !== 'table'"
                class="state draw-failed"
                role="status"
            >
                <span>{{ $gettext("The chart could not be drawn.") }}</span>
            </p>
            <div
                v-if="layout !== 'table'"
                ref="chart"
                class="chart"
                :class="{ failed: drawFailed }"
                role="img"
                :aria-label="chartLabel"
            ></div>
            <p class="note">
                <span>{{
                    $gettext(
                        "Intensities are not comparable in absolute value across instruments.",
                    )
                }}</span>
            </p>
            <p
                :id="csvNoteId"
                class="note"
            >
                <span>{{
                    $gettext(
                        "The CSV holds the values drawn, treatment included and offset left out: two columns per curve.",
                    )
                }}</span>
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
.xy-workshop {
    display: grid;
    gap: 0.5rem;
}

.xy-workshop .state {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--ink-muted);
}

.xy-workshop .toolbar,
.xy-workshop .layouts {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem 0.5rem;
}

.xy-workshop .layouts {
    gap: 0.25rem;
}

.xy-workshop button,
.xy-workshop select {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
}

.xy-workshop button[aria-pressed="true"] {
    border-color: var(--ink);
    font-weight: 600;
}

.xy-workshop .treatment {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.8125rem;
}

.xy-workshop button:focus-visible,
.xy-workshop select:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.xy-workshop .chart {
    min-block-size: 18rem;
}

.xy-workshop .chart.failed {
    min-block-size: 0;
}

.xy-workshop .note,
.xy-workshop .notes {
    margin: 0;
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.xy-workshop .notes {
    padding-inline-start: 1.25rem;
}

.xy-workshop .retry {
    justify-self: start;
}
</style>
