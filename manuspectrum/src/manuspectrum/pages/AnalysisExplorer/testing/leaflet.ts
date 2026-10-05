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

/**
 * `L.tileLayer.iiif` without the network: an empty layer group, recorded for
 * assertions. Its info.json reads as refused unless `laid` or `size`, when it
 * gives one image size (`size` pixels, 1 by 1 when only `laid`) and the page
 * is laid on the map.
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
        return Object.assign(
            L.layerGroup(),
            served
                ? { _imageSizes: [{ x: served.w, y: served.h }] }
                : laid
                  ? { _imageSizes: [{}] }
                  : {},
        );
    });
    (L.tileLayer as unknown as { iiif: unknown }).iiif = factory;
    return factory;
}

/** Leaflet reads the container size; jsdom reports 0. */
export function sizedContainer(width = 800, height = 600): HTMLDivElement {
    const element = document.createElement("div");
    Object.defineProperty(element, "clientWidth", { value: width });
    Object.defineProperty(element, "clientHeight", { value: height });
    document.body.append(element);
    return element;
}
