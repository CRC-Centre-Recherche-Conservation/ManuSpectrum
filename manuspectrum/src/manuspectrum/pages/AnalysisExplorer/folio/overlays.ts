import L from "leaflet";
import { imageUrl } from "utils/iiif-image";

import {
    markedZones,
    shapeBounds,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import { safeHref } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";

import { boundsOfBox } from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";
import { UNPLACED } from "@/manuspectrum/pages/AnalysisExplorer/folio/registration-store.ts";

import type {
    AnalysisPayload,
    ImageRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { Annotation } from "@/manuspectrum/pages/AnalysisExplorer/folio/document-view.ts";
import type { LatLng } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import type { Quarter } from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";
import type { Registration } from "@/manuspectrum/pages/AnalysisExplorer/folio/registration-store.ts";
import type { Overlay } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export const OVERLAY_SIZE = 2048;
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
    /** The analysis the layer belongs to. */
    analysis: string;
    /** Quarter turns applied by the image service; 0 for a layer that cannot turn. */
    quarter: Quarter;
    /** True when `bounds` is the reader's registered box rather than the zone's. */
    registered: boolean;
    /** True when the image service can turn the layer. */
    canTurn: boolean;
    /** The layer's IIIF image service, when it has one. */
    service?: string | null;
    /** The layer's image reference: the address and the declared size. */
    image?: ImageRef;
    /** The bounding box of the analysis's marked zone on this page. */
    zoneBounds: [LatLng, LatLng];
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
 * an address `safeHref` accepts is returned; null otherwise. `quarter` has
 * the image service turn the image (scaled first, then rotated, so the sides
 * of the bounded size are not swapped); an image with its own URL cannot turn.
 */
export function layerImageUrl(
    image: ImageRef,
    size = OVERLAY_SIZE,
    options?: { fallback?: boolean | "max"; quarter?: Quarter },
): string | null {
    if (image.url) return safeHref(image.url);
    if (image.service) {
        const turned = (url: string): string | null =>
            safeHref(
                url.replace(
                    /\/0\/default\.jpg$/,
                    `/${(options?.quarter ?? 0) * 90}/default.jpg`,
                ),
            );
        if (options?.fallback === "max") {
            return turned(imageUrl(image.service, { size: "max" }));
        }
        if (options?.fallback) {
            const declared = Math.max(image.width, image.height);
            const percent =
                declared > 0
                    ? Math.min(100, Math.round((100 * size) / declared))
                    : 0;
            return turned(
                imageUrl(image.service, {
                    size: percent > 0 ? `pct:${percent}` : "max",
                }),
            );
        }
        const width = image.width > 0 ? Math.min(size, image.width) : size;
        const height = image.height > 0 ? Math.min(size, image.height) : size;
        return turned(imageUrl(image.service, { size: `!${width},${height}` }));
    }
    return null;
}

/** The layer turned by its image service; null for an image without one. */
export function rotatedImageUrl(
    image: ImageRef,
    quarter: Quarter,
    size = OVERLAY_SIZE,
): string | null {
    return image.service ? layerImageUrl(image, size, { quarter }) : null;
}

/**
 * The addresses to try for a layer image, in order, none twice: bounded
 * `!w,h` (level 2), `pct:n` (level 1), `max` (level 0), each turned by
 * `quarter`. An image with its own URL has one; no usable address, none.
 */
export function layerImageChain(
    image: ImageRef,
    size = OVERLAY_SIZE,
    quarter: Quarter = 0,
): string[] {
    const steps = [
        layerImageUrl(image, size, { quarter }),
        layerImageUrl(image, size, { fallback: true, quarter }),
        layerImageUrl(image, size, { fallback: "max", quarter }),
    ];
    return steps.filter(
        (url, index): url is string =>
            url !== null && steps.indexOf(url) === index,
    );
}

/**
 * The imaging layers of the open analysis that are switched on. Each lies in
 * its registered box, turned by its quarter, when `place.registration` is
 * for `place.canvas` and holds a box (`UNPLACED` marks an entry that holds
 * only a capture); otherwise it is stretched into the bounding box of the
 * analysis's marked zone on this page (`markedZones`; indicative). An analysis
 * with only a point here lays nothing.
 */
export function folioOverlays(
    analysis: AnalysisPayload | null,
    overlays: Record<string, Overlay>,
    annotations: readonly Annotation[],
    place?: { canvas: string | null; registration: Registration | null },
): FolioOverlay[] {
    if (!analysis) return [];
    const zone = markedZones(annotations).find(
        (entry) => entry.analysis === analysis.id,
    );
    const bounds = zone ? shapeBounds(zone.shape) : null;
    if (!bounds) return [];
    const held = place?.registration ?? null;
    const registered =
        held !== null &&
        held.canvas === place?.canvas &&
        !(held.box.w === UNPLACED.w && held.box.h === UNPLACED.h);
    const result: FolioOverlay[] = [];
    for (const file of analysis.files) {
        for (const layer of file.layers) {
            const key = overlayKey(analysis.id, layer.index);
            const setting = overlays[key];
            const canTurn = layer.image.service !== null;
            const quarter: Quarter = registered && canTurn ? held.quarter : 0;
            const chain = layerImageChain(layer.image, OVERLAY_SIZE, quarter);
            const url = chain[0] ?? null;
            if (setting?.on && url) {
                result.push({
                    key,
                    url,
                    fallbackUrls: chain.slice(1),
                    bounds: registered ? boundsOfBox(held.box) : bounds,
                    opacity: setting.opacity,
                    label: layer.label,
                    analysis: analysis.id,
                    quarter,
                    registered,
                    canTurn,
                    service: layer.image.service,
                    image: layer.image,
                    zoneBounds: bounds,
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

const HASH_OFFSET = 0x811c9dc5;
const HASH_PRIME = 0x01000193;
const HASH_RADIX = 36;

/**
 * A short stable key of any text (32-bit FNV-1a in base 36), for a pane
 * named after an id that `overlayPane` would otherwise sanitise: `…/c_1` and
 * `…/c-1` give different keys.
 */
export function paneKey(text: string): string {
    let hash = HASH_OFFSET;
    for (let index = 0; index < text.length; index += 1) {
        hash = Math.imul(hash ^ text.charCodeAt(index), HASH_PRIME);
    }
    return (hash >>> 0).toString(HASH_RADIX);
}

/** Takes a pane made by `overlayPane` off the map; nothing when it has none of that name. */
export function removeOverlayPane(map: L.Map, name: string): void {
    const pane = map.getPane(name);
    if (!pane) return;
    pane.remove();
    delete (map as unknown as { _panes: Record<string, HTMLElement> })._panes[
        name
    ];
}

/** leaflet-side-by-side clips `layer.getContainer()`: a laid layer answers with its own pane. */
export function curtainable<T extends L.Layer>(layer: T, pane: HTMLElement): T {
    (layer as T & { getContainer?: () => HTMLElement }).getContainer = () =>
        pane;
    return layer;
}
