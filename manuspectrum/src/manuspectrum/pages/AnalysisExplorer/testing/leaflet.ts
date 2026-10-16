import L from "leaflet";
import { vi } from "vitest";

interface ServedSize {
    w: number;
    h: number;
}

/**
 * Spec helpers for the folio. jsdom has no `SVGSVGElement.createSVGRect`, so
 * Leaflet builds no SVG renderer unless each spec patches it in a
 * `vi.hoisted` block, which runs before this module imports Leaflet.
 */

const TILE_SIZE = 256;

/** leaflet-iiif 3.0.0's `maxNativeZoom`: `ceil(log2(max(w, h) / tileSize))`, at least 0. */
export function maxNativeZoomOf(size: ServedSize): number {
    return Math.max(
        Math.ceil(Math.log2(size.w / TILE_SIZE)),
        Math.ceil(Math.log2(size.h / TILE_SIZE)),
        0,
    );
}

/**
 * `L.tileLayer.iiif` without the network: an empty layer group, recorded for
 * assertions. Its info.json reads as refused unless `laid` or `size`, when it
 * gives one image size (`size` pixels, 1 by 1 when only `laid`) and the page
 * is laid on the map. A served layer carries leaflet-iiif's `maxNativeZoom`
 * (`maxNativeZoomOf`), as the plugin sets it on the layer and its options.
 */
export function stubIiifLayer({
    laid = false,
    size = null,
}: {
    laid?: boolean;
    /** One size for every page, or the size of the page whose info.json URL is given. */
    size?: ServedSize | ((infoUrl: string) => ServedSize) | null;
} = {}): ReturnType<typeof vi.fn> {
    const factory = vi.fn((infoUrl: string) => {
        const served = typeof size === "function" ? size(infoUrl) : size;
        const layer = Object.assign(
            L.layerGroup(),
            served
                ? {
                      _imageSizes: [{ x: served.w, y: served.h }],
                      maxNativeZoom: maxNativeZoomOf(served),
                      _served: served,
                  }
                : laid
                  ? { _imageSizes: [{}] }
                  : {},
        );
        if (served) {
            Object.assign(layer.options ?? {}, {
                maxNativeZoom: maxNativeZoomOf(served),
            });
        }
        return layer;
    });
    (L.tileLayer as unknown as { iiif: unknown }).iiif = factory;
    return factory;
}

/**
 * The extent, in CRS units, a laid layer spans: an image overlay's bounds, or
 * a `stubIiifLayer` layer by leaflet-iiif 3.0.0's rule, `size / 2^(maxNativeZoom
 * - zoomOffset)` (`folio/scale-group.spec.ts` measures that rule on the real
 * plugin).
 */
export function drawnExtent(layer: L.Layer): ServedSize {
    if (layer instanceof L.ImageOverlay) {
        const bounds = layer.getBounds();
        return {
            w: bounds.getEast() - bounds.getWest(),
            h: bounds.getNorth() - bounds.getSouth(),
        };
    }
    const stub = layer as L.Layer & {
        _served: ServedSize;
        maxNativeZoom: number;
        options: { zoomOffset?: number };
    };
    const factor = 2 ** (stub.maxNativeZoom - (stub.options.zoomOffset ?? 0));
    return { w: stub._served.w / factor, h: stub._served.h / factor };
}

/** Leaflet reads the container size; jsdom reports 0. */
export function sizedContainer(width = 800, height = 600): HTMLDivElement {
    const element = document.createElement("div");
    Object.defineProperty(element, "clientWidth", { value: width });
    Object.defineProperty(element, "clientHeight", { value: height });
    document.body.append(element);
    return element;
}

/**
 * `L.control.sideBySide` without the plugin (specs mock `leaflet-side-by-side`):
 * a control that records nothing and sits at 400 px.
 */
export function stubSideBySide(): ReturnType<typeof vi.fn> {
    const factory = vi.fn(() => {
        const control = {
            addTo: vi.fn(() => control),
            remove: vi.fn(),
            setLeftLayers: vi.fn(() => control),
            setRightLayers: vi.fn(() => control),
            getPosition: () => 400,
            _range: document.createElement("input"),
        };
        return control;
    });
    (L.control as unknown as { sideBySide: unknown }).sideBySide = factory;
    return factory;
}
