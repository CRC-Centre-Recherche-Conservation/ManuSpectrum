import { infoJsonUrl } from "utils/iiif-image";

import {
    OVERLAY_SIZE,
    layerImageChain,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import {
    captureRegion,
    captureUrl,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";

import type { ImageRef } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    Box,
    Quarter,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";
import type { LatLng } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";

const PROBE_TIMEOUT_MS = 15000;

/** Why a capture was not taken: the box leaves the page, or the folio or its image server did not give it. */
export type CaptureFailure = "off-page" | "no-page" | "server";

/**
 * The IIIF url of the folio region under a layer's box, asked at the layer's
 * own size at most with the layer's turn undone; `width` and `height` are the
 * layer's own size, the one the capture is laid at (the region's own, turned
 * back, when the layer's is unknown: a size of 0). Refused with `no-page`
 * without a laid page or a service, and with `off-page` unless the box lies
 * wholly on the page.
 */
export function planCapture(input: {
    page: { bounds: [LatLng, LatLng]; served: { w: number; h: number } } | null;
    service: string | null;
    box: Box;
    quarter: Quarter;
    layerSize: { w: number; h: number };
}):
    | { url: string; width: number; height: number }
    | { refused: "no-page" | "off-page" } {
    if (!input.page || !input.service) return { refused: "no-page" };
    const region = captureRegion(input.box, input.page);
    if (!region) return { refused: "off-page" };
    const known = input.layerSize.w > 0 && input.layerSize.h > 0;
    const odd = input.quarter % 2 === 1;
    const size = known
        ? input.layerSize
        : { w: odd ? region.h : region.w, h: odd ? region.w : region.h };
    return {
        url: captureUrl(input.service, region, size, input.quarter),
        width: Math.round(size.w),
        height: Math.round(size.h),
    };
}

/** A signal that aborts after the probe timeout; none where the browser lacks `AbortSignal.timeout`. */
function timeoutSignal(): AbortSignal | undefined {
    return typeof AbortSignal.timeout === "function"
        ? AbortSignal.timeout(PROBE_TIMEOUT_MS)
        : undefined;
}

/** Whether the image at `url` loads; false on error or after 15 s. */
export function probeImage(url: string): Promise<boolean> {
    return new Promise((resolve) => {
        const image = new Image();
        const timer = setTimeout(() => finish(false), PROBE_TIMEOUT_MS);
        function finish(ok: boolean): void {
            clearTimeout(timer);
            image.onload = null;
            image.onerror = null;
            resolve(ok);
        }
        image.onload = () => finish(true);
        image.onerror = () => finish(false);
        image.src = url;
    });
}

/**
 * Whether the image service can serve the layer turned by `quarter`: one of
 * the addresses the layer would be tried at (`layerImageChain`) loads.
 */
export async function probeTurn(
    image: ImageRef,
    quarter: Quarter,
): Promise<boolean> {
    for (const url of layerImageChain(image, OVERLAY_SIZE, quarter)) {
        if (await probeImage(url)) return true;
    }
    return false;
}

/**
 * The size of a layer's image: its info.json, else the natural size of the
 * laid element (which the image service turned by `quarter`, so an odd
 * quarter swaps its sides); null when neither tells.
 */
export async function layerSizeOf(
    service: string | null,
    element: HTMLImageElement | null,
    quarter: Quarter = 0,
): Promise<{ w: number; h: number } | null> {
    if (service) {
        try {
            const response = await fetch(infoJsonUrl(service), {
                signal: timeoutSignal(),
            });
            if (response.ok) {
                const info = (await response.json()) as {
                    width?: number;
                    height?: number;
                };
                if (info.width && info.height) {
                    return { w: info.width, h: info.height };
                }
            }
        } catch {
            // The element below tells the size.
        }
    }
    if (element?.naturalWidth && element.naturalHeight) {
        const { naturalWidth: w, naturalHeight: h } = element;
        return quarter % 2 === 1 ? { w: h, h: w } : { w, h };
    }
    return null;
}
