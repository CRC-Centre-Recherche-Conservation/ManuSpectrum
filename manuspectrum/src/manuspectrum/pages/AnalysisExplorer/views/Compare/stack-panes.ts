import type { StackLayer } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

/** What one layer's map pane is given. */
export interface PaneAppearance {
    /** Position in the stack; the pane's z-index above the overlay level. */
    order: number;
    shown: boolean;
    /** 0 to 1. */
    opacity: number;
    /** `screen` over the layers below; the first layer shown lies normally. */
    blend: boolean;
    /** The CSS `filter` value: the stack's adjustments, then the hue filter. */
    filter: string;
}

const OVERLAY_Z_INDEX = 400;
const PERCENT = 100;
/** Rec. 709 luminance, the weights of `grayscale()` in linear-light-free CSS filters. */
const LUMA = [0.2126, 0.7152, 0.0722] as const;
const CHANNEL_MAX = 255;

/**
 * The `values` of an SVG `feColorMatrix` that turns an image into its
 * luminance painted in `rgb`, alpha kept: black stays black, white takes
 * the hue, so `screen` over the layers below only adds light.
 */
export function tintMatrix(rgb: readonly [number, number, number]): string {
    const rows = rgb.map((channel) =>
        LUMA.map((weight) => (weight * channel) / CHANNEL_MAX)
            .map((value) => Number(value.toFixed(4)))
            .concat([0, 0]),
    );
    rows.push([0, 0, 0, 1, 0]);
    return rows.map((row) => row.join(" ")).join(" ");
}

/** A pane's filter: the adjustments of the stack, then the reference to the hue's `<filter>`. */
export function paneFilter(adjust: string, filterId: string | null): string {
    return [adjust, filterId ? `url(#${filterId})` : ""]
        .filter((part) => part !== "")
        .join(" ");
}

/**
 * The appearance of each layer of the stack, by canvas. `tintId` gives the
 * id of the hue filter of a canvas, null when it has none; `blinkedOff`
 * is the canvas a blink hides at this moment (the stack itself is not
 * changed).
 */
export function stackAppearances(
    layers: readonly StackLayer[],
    options: {
        filter: string;
        tintId: (canvas: string) => string | null;
        blinkedOff?: string | null;
    },
): Map<string, PaneAppearance> {
    const result = new Map<string, PaneAppearance>();
    let firstShown = true;
    layers.forEach((layer, order) => {
        const shown = layer.on && layer.canvas !== options.blinkedOff;
        result.set(layer.canvas, {
            order,
            shown,
            opacity: layer.opacity / PERCENT,
            blend: layer.on && !firstShown,
            filter: paneFilter(options.filter, options.tintId(layer.canvas)),
        });
        if (layer.on) firstShown = false;
    });
    return result;
}

export function applyAppearance(
    pane: HTMLElement,
    appearance: PaneAppearance,
): void {
    pane.style.opacity = String(appearance.opacity);
    pane.style.setProperty(
        "mix-blend-mode",
        appearance.blend ? "screen" : "normal",
    );
    pane.style.filter = appearance.filter;
    pane.style.zIndex = String(OVERLAY_Z_INDEX + appearance.order);
    pane.style.display = appearance.shown ? "" : "none";
}
