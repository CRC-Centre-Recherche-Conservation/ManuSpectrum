import {
    ANNOTATION_SCALE,
    toLatLng,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";

import type { LatLng } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";

/**
 * A laid layer's place on the folio, in the annotation pixels of `geometry.ts`
 * (Leaflet CRS.Simple × `ANNOTATION_SCALE`, y down), and its clockwise quarter
 * turns. Turning keeps the centre and swaps the sides. Capture regions are read
 * against the page as laid (its bounds and served size), never against the
 * manifest's canvas size, which is not the annotation space.
 */
export type Quarter = 0 | 1 | 2 | 3;
export type Corner = "nw" | "ne" | "se" | "sw";
export interface Box {
    x: number;
    y: number;
    w: number;
    h: number;
}

/** How far a box may run past the page edge (annotation pixels) and still count as on it. */
const PAGE_SLACK = 1;
const MIN_SIDE = 8;

export function boundsOfBox(box: Box): [LatLng, LatLng] {
    return [toLatLng(box.x, box.y + box.h), toLatLng(box.x + box.w, box.y)];
}

export function boxOfBounds([a, b]: [LatLng, LatLng]): Box {
    const xs = [a[1], b[1]].map((value) => value * ANNOTATION_SCALE);
    // `+ 0` turns a negative zero into 0.
    const ys = [a[0], b[0]].map((value) => -value * ANNOTATION_SCALE + 0);
    const x = Math.min(...xs);
    const y = Math.min(...ys);
    return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
}

export function turn(
    box: Box,
    quarter: Quarter,
    by: 1 | -1,
): { box: Box; quarter: Quarter } {
    const cx = box.x + box.w / 2;
    const cy = box.y + box.h / 2;
    return {
        box: { x: cx - box.h / 2, y: cy - box.w / 2, w: box.h, h: box.w },
        quarter: ((((quarter + by) % 4) + 4) % 4) as Quarter,
    };
}

export function moveBox(box: Box, dx: number, dy: number): Box {
    return { ...box, x: box.x + dx, y: box.y + dy };
}

export function scaleBox(
    box: Box,
    factor: number,
    anchor: "centre" | Corner,
): Box {
    const w = Math.max(MIN_SIDE, box.w * factor);
    const h = Math.max(MIN_SIDE, box.h * factor);
    if (anchor === "centre") {
        return {
            x: box.x + (box.w - w) / 2,
            y: box.y + (box.h - h) / 2,
            w,
            h,
        };
    }
    const right = anchor === "ne" || anchor === "se";
    const bottom = anchor === "se" || anchor === "sw";
    return {
        x: right ? box.x + box.w - w : box.x,
        y: bottom ? box.y + box.h - h : box.y,
        w,
        h,
    };
}

/** The opposite corner stays fixed; a side never goes under `MIN_SIDE`. */
export function resizeFromCorner(
    box: Box,
    corner: Corner,
    to: { x: number; y: number },
    keepRatio: boolean,
): Box {
    const fixedX = corner === "nw" || corner === "sw" ? box.x + box.w : box.x;
    const fixedY = corner === "nw" || corner === "ne" ? box.y + box.h : box.y;
    let w = Math.max(MIN_SIDE, Math.abs(to.x - fixedX));
    let h = Math.max(MIN_SIDE, Math.abs(to.y - fixedY));
    if (keepRatio) {
        const ratio = box.w / box.h;
        if (w / h > ratio) h = w / ratio;
        else w = h * ratio;
    }
    return {
        x: to.x < fixedX ? fixedX - w : fixedX,
        y: to.y < fixedY ? fixedY - h : fixedY,
        w,
        h,
    };
}

/**
 * The box in served page pixels; null unless the box lies wholly on the page
 * (within one annotation pixel), since a region cut short would not line up
 * with the layer.
 */
export function captureRegion(
    box: Box,
    page: { bounds: [LatLng, LatLng]; served: { w: number; h: number } },
): { x: number; y: number; w: number; h: number } | null {
    const p = boxOfBounds(page.bounds);
    const slack = PAGE_SLACK;
    if (
        box.x < p.x - slack ||
        box.y < p.y - slack ||
        box.x + box.w > p.x + p.w + slack ||
        box.y + box.h > p.y + p.h + slack
    ) {
        return null;
    }
    const sx = page.served.w / p.w;
    const sy = page.served.h / p.h;
    const x0 = Math.max(box.x, p.x);
    const y0 = Math.max(box.y, p.y);
    const x1 = Math.min(box.x + box.w, p.x + p.w);
    const y1 = Math.min(box.y + box.h, p.y + p.h);
    if (x1 - x0 < 1 || y1 - y0 < 1) return null;
    return {
        x: Math.round((x0 - p.x) * sx),
        y: Math.round((y0 - p.y) * sy),
        w: Math.round((x1 - x0) * sx),
        h: Math.round((y1 - y0) * sy),
    };
}

/**
 * A region of the page with the layer's turn undone, asked at the region's own
 * size or, when that is larger, scaled down to fit `size` (the layer's own
 * size, the one the photo has once turned back) with the region's
 * proportions; the server never scales up. IIIF scales the region before it
 * rotates it, so the size asked is in the folio's orientation while the fit
 * is judged in the layer's: an odd turn swaps the sides of the region for the
 * fit. The image that comes back has the layer's orientation.
 */
export function captureUrl(
    service: string,
    region: { x: number; y: number; w: number; h: number },
    size: { w: number; h: number },
    quarter: Quarter,
): string {
    const back = ((4 - quarter) % 4) * 90;
    const odd = quarter % 2 === 1;
    const turnedW = odd ? region.h : region.w;
    const turnedH = odd ? region.w : region.h;
    const fit =
        size.w > 0 && size.h > 0
            ? Math.min(1, size.w / turnedW, size.h / turnedH)
            : 1;
    const w = Math.max(1, Math.round(region.w * fit));
    const h = Math.max(1, Math.round(region.h * fit));
    return `${service.replace(/\/$/, "")}/${region.x},${region.y},${region.w},${region.h}/${w},${h}/${back}/default.jpg`;
}
