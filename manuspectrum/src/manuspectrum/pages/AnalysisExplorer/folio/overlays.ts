import L from "leaflet";
import { imageUrl } from "utils/iiif-image";

import {
    markedZones,
    shapeBounds,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import { safeHref } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";

import type {
    AnalysisPayload,
    ImageRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { Annotation } from "@/manuspectrum/pages/AnalysisExplorer/folio/document-view.ts";
import type { LatLng } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import type { Overlay } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const OVERLAY_SIZE = 2048;
// Leaflet's own overlay pane level: a laid layer covers the zone outlines, as it did inside that pane.
const OVERLAY_PANE_Z_INDEX = "400";

export interface FolioOverlay {
    key: string;
    url: string;
    /**
     * The addresses `laidLayers` tries in turn, once each, when `url` fails
     * to load (`layerImageChain` after its first); empty for an `image.url`.
     */
    fallbackUrls: string[];
    bounds: [LatLng, LatLng];
    opacity: number;
    label: string;
}

/** The key of a layer's settings in `store.overlays`. */
export function overlayKey(analysisId: string, index: number): string {
    return `${analysisId}:${index}`;
}

/**
 * The layer image: its own URL, else the IIIF image service at most `size` px
 * on a side and never beyond the image's own declared size (servers refuse
 * to scale up); a declared size left at 0 is unknown. `fallback: true` asks
 * for the same image as a percentage of the size the server really holds,
 * `pct:min(100, 100 × size / declared largest side)` (`max` when no size is
 * declared): a stale declared size cannot make it an upscale. `fallback:
 * "max"` asks for the full image, the only size a level-0 server gives. Only
 * an address `safeHref` accepts is returned; null otherwise.
 */
export function layerImageUrl(
    image: ImageRef,
    size = OVERLAY_SIZE,
    options?: { fallback?: boolean | "max" },
): string | null {
    if (image.url) return safeHref(image.url);
    if (image.service) {
        if (options?.fallback === "max") {
            return safeHref(imageUrl(image.service, { size: "max" }));
        }
        if (options?.fallback) {
            const declared = Math.max(image.width, image.height);
            const percent =
                declared > 0
                    ? Math.min(100, Math.round((100 * size) / declared))
                    : 0;
            return safeHref(
                imageUrl(image.service, {
                    size: percent > 0 ? `pct:${percent}` : "max",
                }),
            );
        }
        const width = image.width > 0 ? Math.min(size, image.width) : size;
        const height = image.height > 0 ? Math.min(size, image.height) : size;
        return safeHref(
            imageUrl(image.service, { size: `!${width},${height}` }),
        );
    }
    return null;
}

/**
 * The addresses to try for a layer image, in order, none twice: bounded
 * `!w,h` (level 2), `pct:n` (level 1), `max` (level 0). An image with its
 * own URL has one; no usable address, none.
 */
export function layerImageChain(
    image: ImageRef,
    size = OVERLAY_SIZE,
): string[] {
    const steps = [
        layerImageUrl(image, size),
        layerImageUrl(image, size, { fallback: true }),
        layerImageUrl(image, size, { fallback: "max" }),
    ];
    return steps.filter(
        (url, index): url is string =>
            url !== null && steps.indexOf(url) === index,
    );
}

/**
 * The imaging layers of the open analysis that are switched on, each stretched
 * into the bounding box of the analysis's marked zone on this page
 * (`markedZones`; indicative, not registered). An analysis with only a point
 * here lays nothing.
 */
export function folioOverlays(
    analysis: AnalysisPayload | null,
    overlays: Record<string, Overlay>,
    annotations: readonly Annotation[],
): FolioOverlay[] {
    if (!analysis) return [];
    const zone = markedZones(annotations).find(
        (entry) => entry.analysis === analysis.id,
    );
    const bounds = zone ? shapeBounds(zone.shape) : null;
    if (!bounds) return [];
    const result: FolioOverlay[] = [];
    for (const file of analysis.files) {
        for (const layer of file.layers) {
            const key = overlayKey(analysis.id, layer.index);
            const setting = overlays[key];
            const url = layerImageUrl(layer.image);
            if (setting?.on && url) {
                result.push({
                    key,
                    url,
                    fallbackUrls: layerImageChain(layer.image).slice(1),
                    bounds,
                    opacity: setting.opacity,
                    label: layer.label,
                });
            }
        }
    }
    return result;
}

/**
 * The name of the map pane of one laid layer, created on first use at the level of the
 * overlay pane. leaflet-side-by-side computes its clip rectangle in layer-pane
 * coordinates: right for a pane at the layer origin, wrong for an image
 * overlay's own `<img>`, which sits at the image's top-left corner.
 */
export function overlayPane(map: L.Map, key: string): string {
    const name = `folio-overlay-${key.replace(/[^A-Za-z0-9-]/g, "-")}`;
    if (!map.getPane(name)) {
        map.createPane(name).style.zIndex = OVERLAY_PANE_Z_INDEX;
    }
    return name;
}

/** leaflet-side-by-side clips `layer.getContainer()`: a laid layer answers with its own pane. */
export function curtainable(
    layer: L.ImageOverlay,
    pane: HTMLElement,
): L.ImageOverlay {
    (
        layer as L.ImageOverlay & {
            getContainer?: () => HTMLElement;
        }
    ).getContainer = () => pane;
    return layer;
}
