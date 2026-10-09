import { imageUrl } from "utils/iiif-image";

import {
    ANNOTATION_SCALE,
    toLatLng,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";

import type { LatLng } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import type { ImageRef } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

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

const MIN_SIDE = 8;
const LAYER_SIZE = 2048;

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
 * The layer turned by the image service. The bounded size `!w,h` is applied
 * before the rotation, so an odd quarter swaps the two sides.
 */
export function rotatedImageUrl(
    image: ImageRef,
    quarter: Quarter,
    size = LAYER_SIZE,
): string | null {
    if (!image.service) return null;
    const w = Math.min(size, image.width || size);
    const h = Math.min(size, image.height || size);
    const sides = quarter % 2 === 1 ? `!${h},${w}` : `!${w},${h}`;
    return imageUrl(image.service, { size: sides }).replace(
        /\/0\/default\.jpg$/,
        `/${quarter * 90}/default.jpg`,
    );
}

/** The box in served page pixels, clamped to the page; null when it misses it. */
export function captureRegion(
    box: Box,
    page: { bounds: [LatLng, LatLng]; served: { w: number; h: number } },
): { x: number; y: number; w: number; h: number } | null {
    const p = boxOfBounds(page.bounds);
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
 * A region of the page with the layer's turn undone. `size` is the layer's own
 * size, the one the photo has once turned back; IIIF scales the region before
 * it rotates it, so an odd turn asks for the sides swapped.
 */
export function captureUrl(
    service: string,
    region: { x: number; y: number; w: number; h: number },
    size: { w: number; h: number },
    quarter: Quarter,
): string {
    const back = ((4 - quarter) % 4) * 90;
    const [w, h] = quarter % 2 === 1 ? [size.h, size.w] : [size.w, size.h];
    return `${service.replace(/\/$/, "")}/${region.x},${region.y},${region.w},${region.h}/${Math.round(w)},${Math.round(h)}/${back}/default.jpg`;
}
