import L from "leaflet";

import { handleClearance } from "@/manuspectrum/pages/AnalysisExplorer/folio/adjust-layer.ts";

import type { LatLng } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";

// Above Leaflet's panes (up to 700) and level with the folio's own controls.
const CONTROL_Z_INDEX = "1000";

export interface AnchoredControl {
    /**
     * Keeps the element's top-right corner on the top-right corner of
     * `bounds`, `stack` pixels lower (the room of the controls laid before it).
     * With `above`, the element sits instead right above the top edge of
     * `bounds`, clear of the handles on its corners, and `stack` is ignored;
     * under the bottom edge instead when the top edge leaves no room above.
     */
    place(bounds: [LatLng, LatLng], stack?: number, above?: boolean): void;
    /** Stops following the map and takes the element off it. */
    remove(): void;
}

/**
 * Keeps `element`, a child of the map's container, on the top-right corner of
 * a rectangle of the map: placed in container pixels, again on every `zoom`,
 * `move` and `resize`, and held inside the container so a corner scrolled out
 * of view leaves the control at the nearest edge. Clicks, double clicks and
 * wheel turns on it do not reach the map. It is placed again whenever its own
 * size changes (its content arrives after it is placed).
 */
export function anchoredControl(
    map: L.Map,
    element: HTMLElement,
): AnchoredControl {
    let bounds: [LatLng, LatLng] | null = null;
    let offset = 0;
    let above = false;
    element.style.position = "absolute";
    element.style.zIndex = CONTROL_Z_INDEX;
    L.DomEvent.disableClickPropagation(element);
    L.DomEvent.disableScrollPropagation(element);

    function reposition(): void {
        if (!bounds) return;
        const corner = map.latLngToContainerPoint([
            Math.max(bounds[0][0], bounds[1][0]),
            Math.max(bounds[0][1], bounds[1][1]),
        ]);
        const size = map.getSize();
        const maxLeft = Math.max(size.x - element.offsetWidth, 0);
        const maxTop = Math.max(size.y - element.offsetHeight, 0);
        const left = Math.min(
            Math.max(corner.x - element.offsetWidth, 0),
            maxLeft,
        );
        let wanted = corner.y + offset;
        if (above) {
            wanted = corner.y - element.offsetHeight - handleClearance();
            if (wanted < 0) {
                const bottom = map.latLngToContainerPoint([
                    Math.min(bounds[0][0], bounds[1][0]),
                    Math.min(bounds[0][1], bounds[1][1]),
                ]);
                wanted = bottom.y + handleClearance();
            }
        }
        const top = Math.min(Math.max(wanted, 0), maxTop);
        element.style.left = `${left}px`;
        element.style.top = `${top}px`;
    }

    map.on("zoom move resize", reposition);
    const observer =
        typeof ResizeObserver === "undefined"
            ? null
            : new ResizeObserver(reposition);
    observer?.observe(element);

    return {
        place(next, stack = 0, over = false) {
            bounds = next;
            offset = stack;
            above = over;
            reposition();
        },
        remove() {
            map.off("zoom move resize", reposition);
            observer?.disconnect();
            bounds = null;
            element.remove();
        },
    };
}
