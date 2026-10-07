<script setup lang="ts">
import {
    computed,
    inject,
    nextTick,
    onBeforeUnmount,
    ref,
    useId,
    useTemplateRef,
    watch,
} from "vue";
import { useGettext } from "vue3-gettext";
import { deriveAxisLabel } from "utils/xy-transforms";
import { BASE_VIEW } from "utils/xy-views";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
import LoadingSpinner from "@/manuspectrum/pages/AnalysisExplorer/components/LoadingSpinner.vue";
import XyCurveList from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/XyCurveList.vue";
import XyLegend from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/XyLegend.vue";

import { useSeriesSet } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSeriesSet.ts";
import { useWindowActions } from "@/manuspectrum/pages/AnalysisExplorer/composables/useWindowActions.ts";
import {
    LINKED_SELECTION_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisNode,
    canvasNode,
    fileNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import {
    annotationLabels,
    viewLabels,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/treatment-labels.ts";
import {
    EXPORT_TITLE_ROOM,
    annotationOpacities,
    exportFigure,
    hoverTemplatesFor,
    multiplesFigure,
    paintOf,
    stackedFigure,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop-figure.ts";
import {
    curveLook,
    curveState,
    extent,
    hoverModeFor,
    openingLayout,
    outOfRange,
    ranksInSlot,
    restyleUpdate,
    sharedViews,
    slipZoom,
    treat,
    undoZoom,
    visibleCurveCount,
    workshopCsv,
    zoomedAfter,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";
import { firstStoredTitle } from "@/manuspectrum/pages/AnalysisExplorer/xy/axis-titles.ts";
import { loadPlotly } from "@/manuspectrum/pages/AnalysisExplorer/xy/plotly.ts";
import {
    WORKSHOP_CONFIG,
    readPlotTheme,
    resetAxes,
    whenFontsReady,
} from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

import type { PlotMouseEvent } from "plotly.js";
import type { IconName } from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import type { XyView } from "utils/xy-views";
import type { SeriesResult } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSeriesSet.ts";
import type { PreviewEvent } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { WindowAction } from "@/manuspectrum/pages/AnalysisExplorer/composables/useWindowActions.ts";
import type {
    LegendEyeEvent,
    LegendPreviewEvent,
    LegendToggleEvent,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/XyLegend.vue";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";
import type { FileLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";
import type {
    Figure,
    FigureCurve,
    FigureInput,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop-figure.ts";
import type {
    AxisView,
    CurveRow,
    CurveState,
    Extent,
    LegendGroup,
    WorkshopLayout,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";
import type { PlotTheme } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

type PlotlyModule = Awaited<ReturnType<typeof loadPlotly>>;

interface Curve extends FigureCurve {
    line: FileLine;
    xRange: Extent | null;
    xReversed: boolean;
}

/** A chart Plotly drew: it can bind handlers to its events. */
interface PlotlyTarget extends HTMLElement {
    on?: (name: string, handler: (event: never) => void) => void;
}

/** What Plotly keeps of an axis it drew, as `_fullLayout` holds it. */
interface DrawnAxis {
    range?: unknown[];
    autorange?: boolean | string;
    _length?: number;
}

const AXIS_NAME = /^[xy]axis\d*$/;

/** The layouts drawn as a chart, and their icons; the table is a toggle of its own. */
const CHART_LAYOUTS: Readonly<
    Record<Exclude<WorkshopLayout, "table">, IconName>
> = {
    overlay: "chart-line",
    offset: "bars",
    multiples: "th-large",
};

/** The pixel mapping of an axis Plotly passes with a hovered point. */
interface HoverAxis {
    l2p?: (value: number) => number;
    _offset?: number;
}

const PNG_FILE = "spectra.png";
const CSV_FILE = "spectra.csv";
const DEFAULT_PNG_WIDTH = 960;
const DEFAULT_PNG_HEIGHT = 540;
/** Room on the right of the exported figure for its legend. */
const PNG_LEGEND_ROOM = 240;
const REM = 16;
const DEFAULT_POINTER = "mouse";

/**
 * The XY workshop of a Compare window (§10, D51, D61, D62): every point of
 * every readable spectrum of the window, lines only. A curve takes the
 * hue of its order in the window (twelve solid hues, then the same dashed,
 * then dotted; `curveLook`), the same while files load and never
 * recoloured by the focus. It carries its label at the visual end of the first file of its slot.
 * Overlaid, offset (each curve lifted above the one before it, no Y tick
 * labels, the real values on hover), in a grid of small multiples (one
 * panel per slot, the X axes zoomed together, each with its own compact
 * hover box; the default above eight curves) or as a table. Hover lists every curve currently
 * answering it (`"x unified"`) up to `UNIFIED_HOVER_MAX_CURVES`, falling
 * back to `"closest"` beyond; the mode is a relayout of the curves shown,
 * never a redraw
 * (`restyle`). A treatment of `utils/xy-views.js` runs on every curve and
 * names itself in the Y title. The legend is HTML (`XyLegend`); the
 * exported PNG draws Plotly's, with a title (the window's `title`) and a
 * source line.
 *
 * Its window's header carries its actions (`useWindowActions`): « Reset
 * the zoom » once the chart is zoomed, the PNG, the CSV (what it holds in
 * its tooltip) and the table layout as a toggle, which gives back the
 * chart layout left. The chart layouts are a group of icon toggles above
 * the chart, next to the treatment menu.
 *
 * The linked selection of Compare (`LINKED_SELECTION_KEY`) reaches the
 * chart through its `an:` and `file:` nodes: while it holds something, the
 * curves it links are emphasised — thicker (2.5 px), never recoloured: a
 * curve always keeps its own per-window hue and dash, whatever links it or
 * previews it, so the chart stays readable with several pins active. A
 * curve the selection does not link is hidden (« Hide », the default) or
 * dimmed to grey at reduced opacity (« Dim », the toolbar's « Unlinked
 * spectra » switch, shown only while a focus is active), its legend entry
 * kept; a preview emphasises what it links, hidden or dimmed or not.
 * Independently of the focus, the legend's eye hides or shows a curve
 * (`store.hiddenCurves`, per window, for the tab only): an eye-hidden curve
 * is folded into `"hidden"` before it reaches the paint
 * (`effectiveStates`), so it wins over whatever the focus would otherwise
 * show, hover included. These changes only restyle the drawn chart, once
 * per frame (`Plotly.restyle` of style attributes — colour, dash, width,
 * opacity and hoverinfo are all `editType: "style"` in
 * plotly.js-cartesian-dist 4.0.0 — `Plotly.relayout` of annotation
 * opacities and of the hovermode). A curve that does not answer hover has
 * an empty `hovertemplate` (`hoverTemplatesFor`): with a template set,
 * Plotly does not read `hoverinfo: "skip"` into the trace.
 * A click on a legend entry or a curve toggles its node; a mouse resting
 * on either previews it. A press on the chart that slips into a zoom box
 * narrower than `MIN_ZOOM_PX` is the click it was meant to be: the axes go
 * back to the view the press began on and the curve under it, if any,
 * toggles.
 *
 * A file over the server's ceiling, missing or empty is named and left
 * out. A chart Plotly cannot draw says so in the window. The chart follows
 * its window's size (`WINDOW_RESIZE_KEY`) only when its own size changed,
 * and is then drawn again for the size (labels, panels); small multiples
 * that no longer need a height of their own are drawn once more at the
 * size the chart shrinks to. The table layout and the unmount purge it,
 * and end a preview the chart or its legend started; a drawing that ends
 * after the unmount is purged too.
 */
const props = defineProps<{
    curves: readonly FileLine[];
    title?: string;
    /** Keys the eye-hidden curves in the store; a fallback id when the window opens outside Compare. */
    windowId?: string;
}>();

const resizeTick = inject(WINDOW_RESIZE_KEY, null);
const linked = inject(LINKED_SELECTION_KEY, null);

const { $gettext, $ngettext, interpolate } = useGettext();
const store = useExplorerStore();
const fallbackWindowId = useId();
const windowKey = computed(() => props.windowId ?? fallbackWindowId);
const readable = computed(() =>
    props.curves.filter((curve) => curve.file.previewUrl !== null),
);
const results = useSeriesSet(
    () => readable.value.map((curve) => curve.file.previewUrl ?? ""),
    "full",
);
const chart = useTemplateRef<HTMLDivElement>("chart");
const lang = document.documentElement.lang || "en";

// The Plotly module, the element it drew in and what it drew live outside Vue reactivity.
let plotly: PlotlyModule | null = null;
let drawnOn: HTMLElement | null = null;
let lastFigure: Figure | null = null;
let drawnTheme: PlotTheme | null = null;
/** The curve states the chart shows, joined; a restyle to the same states is skipped. */
let shownStates = "";
/** The annotation opacities the chart shows. */
let shownOpacities: number[] = [];
/** The hovermode the chart shows; a change is a relayout, its hovertemplates restyled to match, never a redraw. */
let shownHoverMode: "x unified" | "closest" = "x unified";
let drawing = false;
let restyleFrame: number | null = null;
const boundCharts = new WeakSet<HTMLElement>();
/** The chart's size when it was last drawn or resized, « width×height ». */
let drawnSize = "";
/** Set on unmount: a drawing still waiting stops, and one that ends late is purged. */
let disposed = false;
/** Whether a preview started here (a curve or a legend entry) is not ended yet. */
let previewing = false;
/** The curve under the mouse, as Plotly last hovered it. */
let hovered: Curve | null = null;
/** The curve under the mouse and the axes shown when the last press on the chart began. */
let press: { curve: Curve | null; axes: Record<string, AxisView> } | null =
    null;

/** The layout the reader picked; null follows the curves. */
const chosenLayout = ref<WorkshopLayout | null>(null);
/** The layout picked before the table, given back when the table is left. */
const layoutBeforeTable = ref<WorkshopLayout | null>(null);
/** The chart shows a zoom of the reader's; « Reset the zoom » is offered. */
const zoomed = ref(false);
const viewKey = ref<string>(BASE_VIEW);
/** Plotly could not be loaded or could not draw the last figure. */
const drawFailed = ref(false);
/** The height small multiples need beyond the window's, in rem; null when they fit. */
const chartHeight = ref<string | null>(null);
/** How an unrelated curve shows while a focus is active; shown only then, defaults to Hide. */
const unrelatedMode = ref<"hide" | "dim">("hide");

/** Each readable file's answer, by preview URL, once the answer is for the files shown. */
const answers = computed(() => {
    const urls = results.loaded.value?.split("\n") ?? [];
    const data = results.data.value ?? [];
    return new Map<string, SeriesResult>(
        urls.map((url, index) => [url, data[index]]),
    );
});
/** Each readable file's rank in its slot, over every curve the window will draw, loaded or not. A curve's order in `readable` picks its colour. */
const ranks = computed(() =>
    ranksInSlot(readable.value.map((line) => line.slot)),
);
const loadedCurves = computed(() =>
    readable.value.flatMap((line, index) => {
        const series = answers.value.get(line.file.previewUrl ?? "")?.series;
        return series
            ? [{ line, series, rank: ranks.value[index], order: index }]
            : [];
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
    return loadedCurves.value.map(({ line, series, rank, order }) => {
        const y = treat(series.x, series.y, view.value);
        return {
            line,
            slot: line.slot,
            analysis: line.analysis.name.value,
            label: `${slotLabel(line.slot)} · ${line.file.name}`,
            fileName: line.file.name,
            rank,
            order,
            x: series.x,
            y,
            xRange: extent(series.x),
            yRange: extent(y),
            xReversed: series.x_reversed,
        };
    });
});
const slots = computed(() =>
    [...new Set(drawn.value.map((curve) => curve.line.slot))].sort(
        (one, other) => one - other,
    ),
);
/** How many files each slot draws. */
const filesInSlot = computed(() => {
    const counts = new Map<number, number>();
    for (const curve of drawn.value) {
        counts.set(curve.line.slot, (counts.get(curve.line.slot) ?? 0) + 1);
    }
    return counts;
});
const layouts = computed<WorkshopLayout[]>(() =>
    slots.value.length > 1
        ? ["overlay", "offset", "multiples", "table"]
        : ["overlay", "offset", "table"],
);
const chartLayouts = computed(() =>
    layouts.value.flatMap((name) =>
        name === "table" ? [] : [{ name, icon: CHART_LAYOUTS[name] }],
    ),
);
const unrelatedModeOptions = computed(() => [
    { value: "hide" as const, label: $gettext("Hide") },
    { value: "dim" as const, label: $gettext("Dim") },
]);
const layout = computed<WorkshopLayout>(() => {
    const wanted = chosenLayout.value ?? openingLayout(drawn.value.length);
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
const offsetTitle = computed(() =>
    titles.value.y
        ? interpolate(
              $gettext("%{title} (offset)"),
              { title: titles.value.y },
              true,
          )
        : $gettext("Intensity (offset)"),
);
const flags = computed(() =>
    outOfRange(drawn.value.map((curve) => curve.xRange)),
);
const selecting = computed(() => (linked?.selection.value.length ?? 0) > 0);
const selected = computed(() => new Set(linked?.selection.value ?? []));
/** How the selection links each drawn curve, through its file or its analysis. */
const levels = computed<(RelationLevel | null)[]>(() =>
    drawn.value.map((curve) => levelIn(linked?.levels.value, curve)),
);
const states = computed<CurveState[]>(() =>
    drawn.value.map((curve, index) =>
        curveState(
            levels.value[index],
            selecting.value,
            levelIn(linked?.previewLevels.value, curve) !== null,
            unrelatedMode.value === "dim",
        ),
    ),
);
/** The curves the legend's eye hid in this window, independent of the focus. */
const hiddenIds = computed(
    () => new Set(store.hiddenCurves[windowKey.value] ?? []),
);
/**
 * `states` with an eye-hidden curve folded into `"hidden"`: the eye wins
 * over the focus, whatever it would otherwise show. Drives the paint, the
 * panel-title opacity and the restyle key alike, so all three agree on what
 * counts as hidden.
 */
const effectiveStates = computed<CurveState[]>(() =>
    states.value.map((state, index) =>
        hiddenIds.value.has(curveId(drawn.value[index])) ? "hidden" : state,
    ),
);
const rows = computed<CurveRow[]>(() =>
    drawn.value.map((curve, index) => ({
        id: curveId(curve),
        label: curve.label,
        analysis: curve.line.analysis.name,
        x: curve.xRange,
        y: curve.yRange,
        outOfRange: flags.value[index],
        relation: selecting.value ? levels.value[index] ?? "none" : undefined,
    })),
);
const legendGroups = computed<LegendGroup[]>(() =>
    slots.value.map((slot) => {
        const indices = drawn.value.flatMap((curve, index) =>
            curve.line.slot === slot ? [index] : [],
        );
        const first = drawn.value[indices[0]];
        const node = analysisNode(first.line.analysis.id);
        const analysis = first.line.analysis;
        return {
            slot,
            label: slotLabel(slot),
            analysis: analysis.name,
            technique: analysis.technique?.code ?? null,
            component: analysis.component?.name ?? null,
            folio: analysis.canvas
                ? linked?.labelOf(canvasNode(analysis.canvas))?.value ?? null
                : null,
            node,
            nodes: [
                node,
                ...indices.map((index) =>
                    fileNode(drawn.value[index].line.file.id),
                ),
            ],
            pressed: selected.value.has(node),
            look: curveLook(first, effectiveStates.value[indices[0]]),
            entries: indices.map((index) => {
                const curve = drawn.value[index];
                const entry = entryNode(curve);
                return {
                    id: curveId(curve),
                    name: curve.line.file.name,
                    slot,
                    look: curveLook(curve, effectiveStates.value[index]),
                    node: entry,
                    nodes: [fileNode(curve.line.file.id), node],
                    pressed: selected.value.has(entry),
                };
            }),
        };
    }),
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
/** Whether every curve drawn is hidden, by the selection or by the legend's eye. */
const allHidden = computed(
    () =>
        effectiveStates.value.length > 0 &&
        effectiveStates.value.every((state) => state === "hidden"),
);
/** What the window says when every curve is hidden: the selection's doing, or the eye's. */
const allHiddenNote = computed(() =>
    selecting.value && states.value.every((state) => state === "hidden")
        ? $gettext(
              "No curve here is linked to the selection; press a legend entry to add it.",
          )
        : $gettext(
              "Every curve is hidden; « Show all spectra » brings them back.",
          ),
);
const csvNote = computed(() =>
    $gettext(
        "The CSV holds the values drawn, treatment included and offset left out: two columns per curve.",
    ),
);

useWindowActions(() => {
    if (drawn.value.length === 0) return [];
    const charted = layout.value !== "table";
    const actions: WindowAction[] = [];
    if (charted && zoomed.value) {
        actions.push({
            id: "reset",
            icon: "refresh",
            label: $gettext("Reset the zoom"),
            run: () => void reset(),
        });
    }
    if (charted) {
        actions.push({
            id: "png",
            icon: "image",
            label: $gettext("Download PNG"),
            run: () => void downloadPng(),
        });
    }
    actions.push(
        {
            id: "csv",
            icon: "download",
            label: $gettext("Download CSV"),
            description: csvNote.value,
            run: downloadCsv,
        },
        {
            id: "table",
            icon: "table",
            label: $gettext("Table"),
            pressed: !charted,
            run: toggleTable,
        },
    );
    return actions;
});

watch([drawn, layout, chart], () => void draw());
watch(layout, (name) => {
    if (name === "table") purgeChart();
});
watch(effectiveStates, () => scheduleRestyle());
watch(
    () => resizeTick?.value,
    () => followSize(),
);
watch(drawn, (curves) => {
    const ids = new Set(curves.map(curveId));
    store.pruneHiddenCurves(windowKey.value, (id) => ids.has(id));
});

onBeforeUnmount(() => {
    disposed = true;
    if (restyleFrame !== null) cancelAnimationFrame(restyleFrame);
    purgeChart();
});

function sizeOf(element: HTMLElement): string {
    return `${element.clientWidth}×${element.clientHeight}`;
}

/** Draws the chart again for its size, when that size is not the one it was drawn at. */
function followSize(): void {
    const element = chart.value;
    if (!plotly || !element || layout.value === "table") return;
    const size = sizeOf(element);
    if (size === drawnSize) return;
    drawnSize = size;
    void resizeChart(element);
}

/** The strongest of the levels; null when none links. */
function strongest(
    found: readonly (RelationLevel | null)[],
): RelationLevel | null {
    if (found.includes("self")) return "self";
    if (found.includes("direct")) return "direct";
    return found.includes("evidence") ? "evidence" : null;
}

function levelIn(
    map: ReadonlyMap<NodeId, RelationLevel> | undefined,
    curve: Curve,
): RelationLevel | null {
    if (!map || map.size === 0) return null;
    return strongest([
        map.get(fileNode(curve.line.file.id)) ?? null,
        map.get(analysisNode(curve.line.analysis.id)) ?? null,
    ]);
}

/** The node a curve toggles: its file when its slot draws several, else its analysis. */
function entryNode(curve: Curve): NodeId {
    return (filesInSlot.value.get(curve.line.slot) ?? 0) > 1
        ? fileNode(curve.line.file.id)
        : analysisNode(curve.line.analysis.id);
}

/** A curve's id in the legend's eye state (`store.hiddenCurves`) and the table's rows. */
function curveId(curve: Curve): string {
    return `${curve.line.key}|${curve.line.file.id}`;
}

/** Frees the chart Plotly drew, and forgets it; a preview started on it or its legend ends. */
function purgeChart(): void {
    if (plotly && drawnOn) {
        plotly.purge(drawnOn);
        boundCharts.delete(drawnOn);
    }
    drawnOn = null;
    lastFigure = null;
    shownStates = "";
    hovered = null;
    press = null;
    if (previewing) linked?.preview(null);
    previewing = false;
}

function layoutName(name: WorkshopLayout): string {
    switch (name) {
        case "overlay":
            return $gettext("Overlay");
        case "offset":
            return $gettext("Offset");
        case "multiples":
            return $gettext("Grid");
        default:
            return $gettext("Table");
    }
}

function viewName(entry: XyView): string {
    return viewNames.value[entry.key] ?? entry.key;
}

/** What the figure is drawn from, for the chart element's size. */
function figureInput(theme: PlotTheme, element: HTMLElement): FigureInput {
    return {
        curves: drawn.value,
        states: effectiveStates.value,
        theme,
        lang,
        titles: { ...titles.value, offset: offsetTitle.value },
        xReversed: xReversed.value,
        width: element.clientWidth,
        height: element.clientHeight,
    };
}

async function draw(): Promise<void> {
    const element = chart.value;
    if (!element || drawn.value.length === 0 || layout.value === "table") {
        return;
    }
    drawing = true;
    /** Small multiples that needed a height of their own and no longer do: the chart shrinks once drawn. */
    let released = false;
    try {
        plotly ??= await loadPlotly();
        if (disposed) return;
        await whenFontsReady();
        if (disposed) return;
        if (drawnOn && drawnOn !== element) purgeChart();
        const theme = readPlotTheme();
        const input = figureInput(theme, element);
        const figure =
            layout.value === "multiples"
                ? multiplesFigure(input)
                : stackedFigure(input, layout.value === "offset");
        released = chartHeight.value !== null && figure.height === null;
        chartHeight.value =
            figure.height === null ? null : `${figure.height / REM}rem`;
        const opacities = annotationOpacities(figure, effectiveStates.value);
        (figure.layout.annotations ?? []).forEach((note, index) => {
            note.opacity = opacities[index];
        });
        lastFigure = figure;
        drawnOn = element;
        drawnTheme = theme;
        drawnSize = sizeOf(element);
        shownStates = effectiveStates.value.join();
        shownOpacities = opacities;
        shownHoverMode = hoverModeFor(visibleCurveCount(effectiveStates.value));
        await plotly.react(
            element,
            figure.data,
            figure.layout,
            WORKSHOP_CONFIG,
        );
        zoomed.value = false;
        if (disposed) {
            plotly.purge(element);
            return;
        }
        bindEvents(element);
        drawFailed.value = false;
    } catch (error: unknown) {
        if (disposed) return;
        drawFailed.value = true;
        console.error("Spectra comparison could not be drawn", error);
    } finally {
        drawing = false;
        if (!disposed) scheduleRestyle();
    }
    if (released && !disposed) {
        await nextTick();
        followSize();
    }
}

async function resizeChart(element: HTMLElement): Promise<void> {
    if (!plotly) return;
    await plotly.Plots.resize(element);
    if (!disposed) await draw();
}

function scheduleRestyle(): void {
    if (restyleFrame !== null) return;
    restyleFrame = requestAnimationFrame(() => {
        restyleFrame = null;
        void restyle();
    });
}

/**
 * Shows the current curve states and hovermode on the drawn chart through
 * style attributes and relayouts only, no redraw; nothing when they are
 * shown already. The hovermode (`hoverModeFor` on the curves currently
 * answering hover) is `layout.hovermode`, a `modebar` `editType` in
 * plotly.js-cartesian-dist 4.0.0 — a relayout, never a recalc — restyled
 * with the hovertemplates that name it (a unified box's compact line, or
 * closest's two-line one; empty for a curve that does not answer hover).
 * Everything here counts as shown once Plotly has taken it: after a failure
 * the next restyle tries it again.
 */
async function restyle(): Promise<void> {
    const element = drawnOn;
    const figure = lastFigure;
    const theme = drawnTheme;
    if (drawing || !plotly || !element || !figure || !theme) return;
    if (figure.order.length !== drawn.value.length) return;
    const key = effectiveStates.value.join();
    if (key === shownStates) return;
    const input = figureInput(theme, element);
    const paints = figure.order.map((index) => paintOf(input, index));
    const mode = hoverModeFor(visibleCurveCount(effectiveStates.value));
    const templates = hoverTemplatesFor(
        input,
        figure.order,
        layout.value === "offset" ? "customdata" : "y",
        mode,
    );
    try {
        await plotly.restyle(
            element,
            restyleUpdate(paints, templates) as unknown as Parameters<
                PlotlyModule["restyle"]
            >[1],
        );
        if (mode !== shownHoverMode) {
            await plotly.relayout(element, { hovermode: mode });
            shownHoverMode = mode;
        }
        const opacities = annotationOpacities(figure, effectiveStates.value);
        const update: Record<string, number> = {};
        opacities.forEach((opacity, index) => {
            if (opacity !== shownOpacities[index]) {
                update[`annotations[${index}].opacity`] = opacity;
            }
        });
        if (Object.keys(update).length > 0) {
            await plotly.relayout(element, update);
        }
        if (lastFigure === figure) {
            shownOpacities = opacities;
            shownStates = key;
        }
    } catch (error: unknown) {
        console.error("Spectra comparison could not be restyled", error);
    }
}

function bindEvents(element: HTMLElement): void {
    const target = element as PlotlyTarget;
    if (boundCharts.has(element) || typeof target.on !== "function") return;
    boundCharts.add(element);
    element.addEventListener("pointerdown", () => {
        press = { curve: hovered, axes: axesOf(element) };
    });
    target.on("plotly_relayout", (update: Record<string, unknown>) => {
        const before = press;
        press = null;
        if (before && plotly && slipZoom(update, before.axes)) {
            void plotly.relayout(element, undoZoom(update, before.axes));
            if (before.curve) toggle(entryNode(before.curve));
            return;
        }
        zoomed.value = zoomedAfter(update, zoomed.value);
    });
    target.on("plotly_hover", (event: PlotMouseEvent) => {
        const curve = hoveredCurve(event);
        hovered = curve;
        if (curve) preview(entryNode(curve), pointerOf(event));
    });
    target.on("plotly_unhover", (event: PlotMouseEvent) => {
        hovered = null;
        preview(null, pointerOf(event));
    });
    target.on("plotly_click", (event: PlotMouseEvent) => {
        const curve = hoveredCurve(event);
        if (curve) toggle(entryNode(curve));
    });
}

/** The axes Plotly shows on `element`, by name: range, autorange and length in pixels. */
function axesOf(element: HTMLElement): Record<string, AxisView> {
    const layout = (element as { _fullLayout?: Record<string, unknown> })
        ._fullLayout;
    const axes: Record<string, AxisView> = {};
    for (const [name, value] of Object.entries(layout ?? {})) {
        const axis = value as DrawnAxis | null;
        if (!AXIS_NAME.test(name) || !Array.isArray(axis?.range)) continue;
        axes[name] = {
            range: [Number(axis.range[0]), Number(axis.range[1])],
            autorange: axis.autorange ?? false,
            length: axis._length ?? 0,
        };
    }
    return axes;
}

function pointerOf(event: PlotMouseEvent): { pointerType: string } {
    const source = event?.event as PointerEvent | undefined;
    return { pointerType: source?.pointerType || DEFAULT_POINTER };
}

/**
 * The curve under the pointer: the one point Plotly names, or, when the
 * hover names every curve at that X, the one drawn nearest the pointer.
 */
function hoveredCurve(event: PlotMouseEvent): Curve | null {
    const figure = lastFigure;
    const points = event?.points ?? [];
    if (!figure || points.length === 0) return null;
    let chosen = points[0];
    if (points.length > 1) {
        const top = drawnOn?.getBoundingClientRect().top ?? 0;
        const pointer = (event.event?.clientY ?? Number.NaN) - top;
        let nearest = Infinity;
        for (const point of points) {
            const axis = point.yaxis as unknown as HoverAxis;
            if (!axis?.l2p || typeof point.y !== "number") continue;
            const distance = Math.abs(
                axis.l2p(point.y) + (axis._offset ?? 0) - pointer,
            );
            if (distance < nearest) {
                nearest = distance;
                chosen = point;
            }
        }
        if (!Number.isFinite(nearest)) return null;
    }
    const index = figure.order[chosen.curveNumber];
    return index === undefined ? null : drawn.value[index] ?? null;
}

function toggle(node: NodeId): void {
    linked?.toggle(node);
}

function onLegendToggle({ node }: LegendToggleEvent): void {
    toggle(node);
}

function onLegendToggleEye({ id }: LegendEyeEvent): void {
    store.toggleCurveVisibility(windowKey.value, id);
}

function onLegendShowAll(): void {
    store.showAllCurves(windowKey.value);
}

function onLegendPreview({
    node,
    pointerType,
    anchor,
}: LegendPreviewEvent): void {
    preview(
        node,
        anchor ? { pointerType, currentTarget: anchor } : { pointerType },
    );
}

function preview(node: NodeId | null, event: PreviewEvent): void {
    linked?.preview(node, event);
    previewing = node !== null;
}

async function reset(): Promise<void> {
    zoomed.value = false;
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

function exportTitle(): string {
    if (props.title) return props.title;
    return titles.value.x && titles.value.y
        ? interpolate(
              $gettext("%{y} against %{x}"),
              { y: titles.value.y, x: titles.value.x },
              true,
          )
        : titles.value.y || titles.value.x;
}

function sourceLine(): string {
    const date = new Intl.DateTimeFormat(lang, { dateStyle: "long" }).format(
        new Date(),
    );
    return interpolate(
        $gettext("Source: ManuSpectrum, %{url}, %{date}"),
        {
            url: `${window.location.origin}${window.location.pathname}`,
            date,
        },
        true,
    );
}

/**
 * The chart as a PNG, on the page's background rather than the transparent
 * one of the screen: the curves as shown (a hidden curve left out), Plotly's
 * legend on the right, a title and a source line.
 */
async function downloadPng(): Promise<void> {
    const element = chart.value;
    const figure = lastFigure;
    const theme = drawnTheme;
    if (!plotly || !element || !figure || !theme) return;
    const input = figureInput(theme, element);
    const paints = figure.order.map((index) => paintOf(input, index));
    try {
        const url = await plotly.toImage(
            exportFigure(figure, paints, theme, {
                title: exportTitle(),
                source: sourceLine(),
            }),
            {
                format: "png",
                width:
                    (element.clientWidth || DEFAULT_PNG_WIDTH) +
                    PNG_LEGEND_ROOM,
                height:
                    (element.clientHeight || DEFAULT_PNG_HEIGHT) +
                    EXPORT_TITLE_ROOM,
            },
        );
        save(url, PNG_FILE);
    } catch (error: unknown) {
        console.error("Spectra comparison could not be exported", error);
    }
}

/** The values drawn, treatment included and offset left out, under a line saying so. */
function downloadCsv(): void {
    const text = workshopCsv(
        drawn.value.map((curve) => ({
            label: curve.label,
            x: curve.x,
            y: curve.y,
        })),
        titles.value.x || "X",
        titles.value.y || "Y",
        csvNote.value,
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

/** Shows the table, or leaves it for the chart layout it replaced. */
function toggleTable(): void {
    if (layout.value === "table") {
        chosenLayout.value = layoutBeforeTable.value;
        return;
    }
    layoutBeforeTable.value = chosenLayout.value;
    chosenLayout.value = "table";
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
                    <IconButton
                        v-for="entry in chartLayouts"
                        :key="entry.name"
                        :data-layout="entry.name"
                        :icon="entry.icon"
                        :label="layoutName(entry.name)"
                        :pressed="layout === entry.name"
                        tip-placement="below"
                        tip-align="start"
                        @click="chooseLayout(entry.name)"
                    />
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
                <div
                    v-if="selecting"
                    class="unrelated-mode"
                >
                    <span>{{ $gettext("Unlinked spectra") }}</span>
                    <span
                        class="segmented"
                        role="group"
                        :aria-label="$gettext('Unlinked spectra')"
                    >
                        <button
                            v-for="option in unrelatedModeOptions"
                            :key="option.value"
                            type="button"
                            :data-mode="option.value"
                            :aria-pressed="
                                unrelatedMode === option.value
                                    ? 'true'
                                    : 'false'
                            "
                            @click="unrelatedMode = option.value"
                        >
                            <span>{{ option.label }}</span>
                        </button>
                    </span>
                </div>
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
            <p
                v-if="allHidden && layout !== 'table'"
                class="note isolated"
            >
                <span>{{ allHiddenNote }}</span>
            </p>
            <div
                v-if="layout !== 'table'"
                class="plot-area"
                :class="{ tall: chartHeight !== null }"
            >
                <div
                    ref="chart"
                    class="chart"
                    :class="{ failed: drawFailed }"
                    :style="
                        chartHeight ? { minBlockSize: chartHeight } : undefined
                    "
                    role="img"
                    :aria-label="chartLabel"
                ></div>
                <XyLegend
                    :groups="legendGroups"
                    :hidden-ids="hiddenIds"
                    @toggle="onLegendToggle"
                    @preview="onLegendPreview"
                    @toggle-eye="onLegendToggleEye"
                    @show-all="onLegendShowAll"
                />
            </div>
            <p class="note">
                <span>{{
                    $gettext(
                        "Intensities are not comparable in absolute value across instruments.",
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
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    block-size: 100%;
    container-type: inline-size;
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
    gap: 0.125rem;
    padding: 0.125rem;
    border: 0.0625rem solid var(--border);
    border-radius: 0.5rem;
    background: var(--bg);
}

.xy-workshop .retry,
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

.xy-workshop .treatment {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.8125rem;
}

.xy-workshop .unrelated-mode {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.75rem;
    color: var(--ink-muted);
}

.xy-workshop .segmented {
    display: inline-flex;
    padding: 0.1875rem;
    border-radius: 999rem;
    background: var(--bg-alt);
    box-shadow: inset 0 0 0 0.0625rem var(--border);
}

.xy-workshop .segmented button {
    min-block-size: 1.75rem;
    padding-inline: 0.75rem;
    border: none;
    border-radius: 999rem;
    background: none;
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.78125rem;
    white-space: nowrap;
    cursor: pointer;
    transition:
        background-color var(--dur-fast, 160ms),
        color var(--dur-fast, 160ms);
}

.xy-workshop .segmented button:hover {
    color: var(--ink);
}

.xy-workshop .segmented button[aria-pressed="true"] {
    background: var(--surface);
    box-shadow:
        0 0.0625rem 0.125rem rgb(26 26 46 / 0.08),
        inset 0 0 0 0.0625rem var(--seg-on-rule);
    color: var(--seg-on-ink);
    font-weight: 600;
}

.xy-workshop .retry:focus-visible,
.xy-workshop select:focus-visible,
.xy-workshop .segmented button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.xy-workshop .plot-area {
    display: grid;
    gap: 0.5rem;
}

.xy-workshop .chart {
    min-block-size: 18rem;
}

@container (min-width: 40rem) {
    .xy-workshop .plot-area {
        flex: 1 1 0;
        grid-template-rows: minmax(0, 1fr);
        grid-template-columns: minmax(0, 1fr) minmax(9rem, 12rem);
        min-block-size: 18rem;
    }

    .xy-workshop .plot-area.tall {
        flex: none;
    }

    .xy-workshop .plot-area .chart {
        min-block-size: 0;
    }

    .xy-workshop .plot-area .xy-legend {
        align-self: start;
        max-block-size: 100%;
        overflow: auto;
    }
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
    align-self: flex-start;
}
</style>
