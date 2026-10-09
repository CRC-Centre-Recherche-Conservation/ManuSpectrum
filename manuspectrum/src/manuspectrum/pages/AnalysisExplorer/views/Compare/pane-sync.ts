import L from "leaflet";

import { OVERZOOM_LEVELS } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import { sameSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";

import type { ServedSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";

/** A pane's map and the image it shows: the size the service serves and the zoom at which that size is 1 px per unit. */
export interface SyncTarget {
    map: L.Map;
    size: ServedSize;
    nativeZoom: number;
}

/**
 * A view of an image, independent of the pane's size: the centre as a
 * fraction of the served size, and the zoom relative to the zoom that fits
 * this image in its pane.
 */
export interface PaneView {
    cx: number;
    cy: number;
    dz: number;
}

/** A view with the size it was read at and the canvas it was read from. */
export interface NormalisedView extends PaneView {
    size: ServedSize;
    origin: string;
}

/** What `applyView` carried: the centre and the zoom, the zoom alone, or nothing. */
export type Applied = "full" | "zoom" | null;

const ANIMATE_OFF = { animate: false } as const;
const EPSILON = 1e-6;
/** The reader may zoom this far out below the fit of the image. */
const ZOOM_OUT_BELOW_FIT = 2;
const FIT_TOLERANCE = 1e-3;
/** Leaflet rounds a pan to whole pixels when its container is resized. */
const CENTRE_TOLERANCE_PX = 2;

/**
 * The zoom that fits the whole image in the pane, or null while the map has
 * no size. Measured from the image's own size, not with Leaflet's
 * `getBoundsZoom`, which stops at the map's minimum and maximum zoom: the
 * minimum is the fit of an earlier, larger pane, and the maximum the native
 * zoom of a small image, so a pane that shrank or an image served smaller
 * than its pane would not be fitted.
 */
export function fitZoomOf(target: SyncTarget): number | null {
    const { map, size, nativeZoom } = target;
    const room = map.getSize();
    if (room.x === 0 || room.y === 0 || !size.w || !size.h) return null;
    const exact =
        nativeZoom + Math.log2(Math.min(room.x / size.w, room.y / size.h));
    if (!Number.isFinite(exact)) return null;
    const snap = L.Browser.any3d ? map.options.zoomSnap : 1;
    if (!snap) return exact;
    // Within 1% of a level, as Leaflet does, the level is not skipped.
    const level = Math.round(exact / (snap / 100)) * (snap / 100);
    return Math.floor(level / snap) * snap;
}

/**
 * Shows the whole image of `target` at `zoom` (its `fitZoomOf`), centred, and
 * lets the reader zoom out `ZOOM_OUT_BELOW_FIT` levels below it. The new
 * minimum is set after the view when it rises, so that `Map.setMinZoom` never
 * zooms to it (an animated zoom that would end over the fit).
 */
export function fitView(target: SyncTarget, zoom: number): void {
    const { map, size, nativeZoom } = target;
    const floor = zoom - ZOOM_OUT_BELOW_FIT;
    if (zoom + OVERZOOM_LEVELS > map.getMaxZoom()) {
        map.setMaxZoom(zoom + OVERZOOM_LEVELS);
    }
    if (floor < map.getMinZoom()) map.setMinZoom(floor);
    map.setView(map.unproject([size.w / 2, size.h / 2], nativeZoom), zoom, {
        animate: false,
    });
    map.setMinZoom(floor);
}

/**
 * Whether the pane still shows the fit of the whole image, centred (or has
 * no size yet, so nothing is fitted): a pane in that state follows its
 * container when it is resized, a pane the reader moved does not.
 */
export function keepsFit(target: SyncTarget): boolean {
    const view = readView(target, "");
    if (!view) return true;
    const { map, size, nativeZoom } = target;
    const middle = map.unproject([size.w / 2, size.h / 2], nativeZoom);
    const off = map.project(middle).distanceTo(map.project(map.getCenter()));
    return Math.abs(view.dz) < FIT_TOLERANCE && off <= CENTRE_TOLERANCE_PX;
}

export function readView(
    target: SyncTarget,
    origin: string,
): NormalisedView | null {
    const fit = fitZoomOf(target);
    if (fit === null) return null;
    const { map, size, nativeZoom } = target;
    const point = map.project(map.getCenter(), nativeZoom);
    return {
        cx: point.x / size.w,
        cy: point.y / size.h,
        dz: map.getZoom() - fit,
        size,
        origin,
    };
}

/**
 * Lays `view` on a pane. Served at the same size, the pane takes the centre
 * and the zoom (an exact overlay); served at another size, it takes the
 * relative zoom only and keeps its own centre, which would otherwise look
 * like the same place when the framings differ.
 */
export function applyView(target: SyncTarget, view: NormalisedView): Applied {
    const fit = fitZoomOf(target);
    if (fit === null) return null;
    const { map, size, nativeZoom } = target;
    const zoom = fit + view.dz;
    if (!sameSize(view.size, size)) {
        if (Math.abs(map.getZoom() - zoom) > EPSILON) {
            map.setZoom(zoom, ANIMATE_OFF);
        }
        return "zoom";
    }
    const centre = map.unproject(
        [view.cx * size.w, view.cy * size.h],
        nativeZoom,
    );
    const here = map.getCenter();
    if (
        Math.abs(map.getZoom() - zoom) > EPSILON ||
        Math.abs(here.lat - centre.lat) > EPSILON ||
        Math.abs(here.lng - centre.lng) > EPSILON
    ) {
        map.setView(centre, zoom, ANIMATE_OFF);
    }
    return "full";
}

export interface PaneWatcher {
    /** Follows a view read from another pane; a view of this pane's own canvas is ignored. */
    apply: (view: NormalisedView) => Applied;
    /** Runs a move of this pane's own (a fit) that is not the reader's and must not be echoed. */
    silently: (move: () => void) => void;
    destroy: () => void;
}

/**
 * Emits the pane's view once per animation frame while the reader moves it.
 * What `apply` and `silently` move is never emitted, so two linked panes do
 * not bounce a view between them.
 */
export function watchPane(options: {
    target: () => SyncTarget | null;
    origin: () => string;
    emit: (view: NormalisedView) => void;
}): PaneWatcher {
    let silent = false;
    let frame: number | null = null;
    let current: L.Map | null = null;

    function flush(): void {
        frame = null;
        const target = options.target();
        const view = target ? readView(target, options.origin()) : null;
        if (view) options.emit(view);
    }

    function onMove(): void {
        if (silent || frame !== null) return;
        frame = requestAnimationFrame(flush);
    }

    function attach(): void {
        const map = options.target()?.map ?? null;
        if (map === current) return;
        current?.off("move", onMove);
        current = map;
        current?.on("move", onMove);
    }

    function silently(move: () => void): void {
        silent = true;
        try {
            move();
        } finally {
            silent = false;
        }
    }

    attach();
    return {
        apply(view) {
            const target = options.target();
            if (!target || view.origin === options.origin()) return null;
            let applied: Applied = null;
            silently(() => {
                applied = applyView(target, view);
            });
            return applied;
        },
        silently(move) {
            attach();
            silently(move);
        },
        destroy() {
            if (frame !== null) cancelAnimationFrame(frame);
            frame = null;
            current?.off("move", onMove);
            current = null;
        },
    };
}
