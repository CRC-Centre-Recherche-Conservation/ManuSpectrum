import { infoJsonUrl } from "utils/iiif-image";

import {
    captureRegion,
    captureUrl,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";

import type {
    Box,
    Quarter,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";
import type { LatLng } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";

const PROBE_TIMEOUT_MS = 15000;

/**
 * The IIIF url of the folio region under a layer's box, asked at the layer's
 * own size with the layer's turn undone; null without a laid page or a
 * service, or when the box misses the page.
 */
export function planCapture(input: {
    page: { bounds: [LatLng, LatLng]; served: { w: number; h: number } } | null;
    service: string | null;
    box: Box;
    quarter: Quarter;
    layerSize: { w: number; h: number };
}): { url: string; width: number; height: number } | null {
    if (!input.page || !input.service) return null;
    const region = captureRegion(input.box, input.page);
    if (!region) return null;
    return {
        url: captureUrl(input.service, region, input.layerSize, input.quarter),
        width: Math.round(input.layerSize.w),
        height: Math.round(input.layerSize.h),
    };
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
            const response = await fetch(infoJsonUrl(service));
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
