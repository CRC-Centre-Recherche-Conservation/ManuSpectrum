import { elementColour } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/element-colour.ts";
import { escapePlotlyText } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

import type { PlotTheme } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

import type { Shape } from "plotly.js";

export type LensShape = Partial<Shape>;

/** Most shapes one window carries; the least important are dropped beyond it. */
export const MAX_LENS_SHAPES = 150;

const TICK_PX = 14;
const MAJOR_INTENSITY = 0.5;
const OVERLAP_OPACITY = 0.22;
/** An overlap is a few tens of eV wide: its centre line keeps it visible on a wide range. */
const OVERLAP_RULE_WIDTH = 4;
const OVERLAP_RULE_OPACITY = 0.5;
const COMPTON_OPACITY = 0.12;
const LABEL_SIZE = 10;

/** Colours the lens draws with: the slot hues of `focus` (indexed by `hue`) and the hue of each element (`elementColour`). */
export type LensTheme = Pick<
    PlotTheme,
    "ink" | "inkMuted" | "focus" | "element" | "fontMono"
>;

/** A vertical line across the panel. `intensity` is relative (0 to 1) within its shell. */
export interface LensLine {
    energy: number;
    label: string;
    intensity: number;
}

/** A pinned element's lines, in the hue of its focus slot. */
export interface FocusLines {
    hue: number;
    /** A previewed element draws thin and dashed. */
    preview?: boolean;
    lines: LensLine[];
}

/** A lens element (any symbol, not in the focus), in its own hue. */
export interface LensElementLines {
    symbol: string;
    lines: LensLine[];
}

/** `rank`: 0 major, 1 minor, 2 trace. */
export interface DeclaredTick {
    symbol: string;
    energy: number;
    rank: number;
    /** The focus slot hue of an element the focus pins; the tick takes it, else the element's own hue. */
    focusHue?: number;
}

/** A dotted bottom tick in the hue of its curve. */
export interface InstrumentTick {
    label: string;
    energy: number;
    colour: string;
}

export interface EnergyBand {
    label: string;
    from: number;
    to: number;
    colour: string;
}

export interface OverlapBand {
    from: number;
    to: number;
    /** Focus hue index of a pinned element of the pair; -1 when none is pinned. */
    hue: number;
    /** The element whose own hue draws the band when none is pinned. */
    symbol: string;
}

/**
 * One Plotly subplot. `suffix` is the axis number (`""` for the first axis,
 * `"2"` for `x2`/`y2`); in overlay there is a single panel.
 */
export interface LensPanel {
    suffix: string;
    /** X extent of the data the panel draws (keV); nothing is drawn outside it. */
    extent: [number, number];
    declared: DeclaredTick[];
    instrument: InstrumentTick[];
    bands: EnergyBand[];
}

export interface LensShapesInput {
    panels: LensPanel[];
    focus: FocusLines[];
    elements: LensElementLines[];
    overlaps: OverlapBand[];
    theme: LensTheme;
}

interface Ranked {
    priority: number;
    shape: LensShape;
}

const RANK_DASH = ["solid", "dash", "dot"] as const;

function inside(energy: number, extent: [number, number]): boolean {
    return energy >= extent[0] && energy <= extent[1];
}

function lineStyle(intensity: number): { width: number; dash: string } {
    return intensity >= MAJOR_INTENSITY
        ? { width: 1.5, dash: "solid" }
        : { width: 1, dash: "dash" };
}

function label(
    text: string,
    colour: string,
    theme: LensTheme,
    textposition: "end" | "start",
): LensShape["label"] {
    return {
        text: escapePlotlyText(text),
        textposition,
        font: { family: theme.fontMono, size: LABEL_SIZE, color: colour },
    };
}

function fullLine(
    panel: LensPanel,
    energy: number,
    colour: string,
    style: { width: number; dash: string },
    text: string,
    theme: LensTheme,
): LensShape {
    return {
        type: "line",
        layer: "below",
        xref: `x${panel.suffix}` as LensShape["xref"],
        yref: `y${panel.suffix} domain` as LensShape["yref"],
        x0: energy,
        x1: energy,
        y0: 0,
        y1: 1,
        line: { color: colour, width: style.width, dash: style.dash as "dash" },
        label: label(text, colour, theme, "end"),
    };
}

function tick(
    panel: LensPanel,
    energy: number,
    top: boolean,
    colour: string,
    dash: string,
    text: string,
    theme: LensTheme,
): LensShape {
    return {
        type: "line",
        layer: "above",
        xref: `x${panel.suffix}` as LensShape["xref"],
        yref: `y${panel.suffix} domain` as LensShape["yref"],
        x0: energy,
        x1: energy,
        ysizemode: "pixel",
        yanchor: top ? 1 : 0,
        y0: top ? -TICK_PX : 0,
        y1: top ? 0 : TICK_PX,
        line: { color: colour, width: 1.5, dash: dash as "dash" },
        label: label(text, colour, theme, top ? "start" : "end"),
    };
}

function band(
    panel: LensPanel,
    from: number,
    to: number,
    colour: string,
    opacity: number,
    text: string | null,
    theme: LensTheme,
): LensShape | null {
    const x0 = Math.max(from, panel.extent[0]);
    const x1 = Math.min(to, panel.extent[1]);
    if (!(x1 > x0)) return null;
    const shape: LensShape = {
        type: "rect",
        layer: "below",
        xref: `x${panel.suffix}` as LensShape["xref"],
        yref: `y${panel.suffix} domain` as LensShape["yref"],
        x0,
        x1,
        y0: 0,
        y1: 1,
        fillcolor: colour,
        opacity,
        line: { width: 0 },
    };
    if (text) shape.label = label(text, colour, theme, "start");
    return shape;
}

function overlapShapes(
    panel: LensPanel,
    entry: OverlapBand,
    theme: LensTheme,
): LensShape[] {
    const colour = theme.focus[entry.hue] ?? elementColour(theme, entry.symbol);
    const rect = band(
        panel,
        entry.from,
        entry.to,
        colour,
        OVERLAP_OPACITY,
        null,
        theme,
    );
    if (!rect) return [];
    const centre = ((rect.x0 as number) + (rect.x1 as number)) / 2;
    const rule: LensShape = {
        type: "line",
        layer: "below",
        xref: rect.xref,
        yref: rect.yref,
        x0: centre,
        x1: centre,
        y0: 0,
        y1: 1,
        opacity: OVERLAP_RULE_OPACITY,
        line: { color: colour, width: OVERLAP_RULE_WIDTH },
    };
    return [rect, rule];
}

/**
 * The Plotly shapes of the XRF lens for one window.
 *
 * Pure and deterministic: equal input gives an equal array, so
 * `shapesKey` lets a caller skip a relayout. Every shape stays inside its
 * panel's X extent (a shape in data coordinates feeds the axis autorange), is
 * placed by `x`/`y … domain` references and never sets `showlegend` (that
 * flag turns a relayout into a full calc). Beyond `MAX_LENS_SHAPES` the least
 * important are dropped: focus lines, lens elements, declared majors, minors,
 * traces, instrument ticks, then bands.
 */
export function lensShapes(input: LensShapesInput): LensShape[] {
    const { theme } = input;
    const ranked: Ranked[] = [];
    const add = (priority: number, shape: LensShape | null) => {
        if (shape) ranked.push({ priority, shape });
    };

    for (const panel of input.panels) {
        for (const group of input.focus) {
            const colour = theme.focus[group.hue] ?? theme.ink;
            for (const line of group.lines) {
                if (!inside(line.energy, panel.extent)) continue;
                const style = group.preview
                    ? { width: 1, dash: "dash" }
                    : lineStyle(line.intensity);
                add(
                    0,
                    fullLine(
                        panel,
                        line.energy,
                        colour,
                        style,
                        line.label,
                        theme,
                    ),
                );
            }
        }
        for (const group of input.elements) {
            for (const line of group.lines) {
                if (!inside(line.energy, panel.extent)) continue;
                add(
                    1,
                    fullLine(
                        panel,
                        line.energy,
                        elementColour(theme, group.symbol),
                        lineStyle(line.intensity),
                        line.label,
                        theme,
                    ),
                );
            }
        }
        for (const entry of panel.declared) {
            if (!inside(entry.energy, panel.extent)) continue;
            const rank = Math.min(Math.max(entry.rank, 0), 2);
            add(
                2 + rank,
                tick(
                    panel,
                    entry.energy,
                    true,
                    entry.focusHue !== undefined && theme.focus[entry.focusHue]
                        ? theme.focus[entry.focusHue]
                        : elementColour(theme, entry.symbol),
                    RANK_DASH[rank],
                    entry.symbol,
                    theme,
                ),
            );
        }
        for (const entry of panel.instrument) {
            if (!inside(entry.energy, panel.extent)) continue;
            add(
                5,
                tick(
                    panel,
                    entry.energy,
                    false,
                    entry.colour,
                    "dot",
                    entry.label,
                    theme,
                ),
            );
        }
        for (const entry of panel.bands) {
            add(
                6,
                band(
                    panel,
                    entry.from,
                    entry.to,
                    entry.colour,
                    COMPTON_OPACITY,
                    entry.label,
                    theme,
                ),
            );
        }
        for (const entry of input.overlaps) {
            for (const shape of overlapShapes(panel, entry, theme)) {
                add(6, shape);
            }
        }
    }

    if (ranked.length <= MAX_LENS_SHAPES) return ranked.map((r) => r.shape);
    const kept = ranked
        .map((entry, index) => ({ ...entry, index }))
        .sort((a, b) => a.priority - b.priority || a.index - b.index)
        .slice(0, MAX_LENS_SHAPES)
        .sort((a, b) => a.index - b.index);
    return kept.map((r) => r.shape);
}

/** A stable string of `shapes`: equal keys mean the same drawing. */
export function shapesKey(shapes: LensShape[]): string {
    return JSON.stringify(shapes);
}
