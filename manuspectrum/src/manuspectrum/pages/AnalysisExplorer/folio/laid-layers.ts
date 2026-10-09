import L from "leaflet";
import "leaflet-side-by-side";

import {
    curtainable,
    overlayPane,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";

import type { FolioOverlay } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";

/** The imaging layers laid on one map, and the curtain (D47) over one of them. */
export interface LaidLayers {
    /**
     * Adds, updates and removes the laid layers by key. The curtain clips
     * the one named by `curtain`; one curtain control lives while a layer is
     * curtained, so its divider keeps its place when the opacity, the
     * curtained layer or the page changes.
     */
    draw(overlays: readonly FolioOverlay[], curtain: string | null): void;
    /** Takes these layers off the map: the next `draw` lays them as new images. */
    forget(keys: Iterable<string>): void;
    /** Takes the curtain off; the layers go with the map. */
    remove(): void;
}

/** A layer that leaves the curtain keeps no clip: its pane may be laid again without it. */
function unclip(event: L.LeafletEvent): void {
    const { layer } = event as L.LeafletEvent & {
        layer: { getContainer?: () => HTMLElement | undefined };
    };
    const container = layer.getContainer?.();
    if (container) container.style.clip = "";
}

/**
 * The laid layers of `map`: each an image overlay in a pane of its own
 * (`overlayPane`, the pane leaflet-side-by-side clips), the curtain being
 * Arches' vendored `leaflet-side-by-side` with its range named
 * `curtainLabel`. A layer whose image does not load is tried at each of
 * `fallbackUrls` in turn, once each; `failed` is called with the key only once
 * the last has also failed, or there was none to try.
 */
export function laidLayers(
    map: L.Map,
    options: { curtainLabel: string; failed: (key: string) => void },
): LaidLayers {
    const images = new Map<string, L.ImageOverlay>();
    /** How many of its `fallbackUrls` each layer has already tried. */
    const fallenBack = new Map<string, number>();
    /** The address each layer was last asked for, apart from any fallback in use. */
    const asked = new Map<string, string>();
    /** The overlay each layer was last drawn from, read by its error handler. */
    const latest = new Map<string, FolioOverlay>();
    let sideBySide: L.SideBySide | null = null;

    function onError(key: string): void {
        const overlay = latest.get(key);
        if (!overlay) return;
        const layer = images.get(overlay.key);
        const tried = fallenBack.get(overlay.key) ?? 0;
        const next = overlay.fallbackUrls[tried];
        if (layer && next) {
            fallenBack.set(overlay.key, tried + 1);
            layer.setUrl(next);
            return;
        }
        options.failed(overlay.key);
    }

    function draw(
        overlays: readonly FolioOverlay[],
        curtain: string | null,
    ): void {
        const wanted = new Set(overlays.map((overlay) => overlay.key));
        for (const [key, layer] of images) {
            if (!wanted.has(key)) {
                layer.remove();
                images.delete(key);
                fallenBack.delete(key);
                asked.delete(key);
                latest.delete(key);
            }
        }
        for (const overlay of overlays) {
            latest.set(overlay.key, overlay);
            const existing = images.get(overlay.key);
            if (existing) {
                existing.setOpacity(overlay.opacity);
                existing.setBounds(L.latLngBounds(overlay.bounds));
                if (asked.get(overlay.key) !== overlay.url) {
                    asked.set(overlay.key, overlay.url);
                    fallenBack.delete(overlay.key);
                    existing.setUrl(overlay.url);
                }
            } else {
                const pane = overlayPane(map, overlay.key);
                const layer = L.imageOverlay(overlay.url, overlay.bounds, {
                    opacity: overlay.opacity,
                    className: "folio-overlay",
                    alt: overlay.label,
                    pane,
                });
                layer.on("error", () => onError(overlay.key));
                asked.set(overlay.key, overlay.url);
                images.set(
                    overlay.key,
                    curtainable(layer.addTo(map), map.getPane(pane)!),
                );
            }
        }
        const under = curtain ? images.get(curtain) : undefined;
        if (!under) {
            sideBySide?.remove();
            sideBySide = null;
        } else if (sideBySide) {
            sideBySide.setRightLayers(under);
        } else {
            sideBySide = L.control
                .sideBySide([], under)
                .addTo(map)
                .on("rightlayerremove", unclip);
            (
                sideBySide as L.SideBySide & { _range?: HTMLElement }
            )._range?.setAttribute("aria-label", options.curtainLabel);
        }
    }

    function forget(keys: Iterable<string>): void {
        for (const key of keys) {
            images.get(key)?.remove();
            images.delete(key);
            fallenBack.delete(key);
            asked.delete(key);
            latest.delete(key);
        }
    }

    function remove(): void {
        sideBySide?.remove();
        sideBySide = null;
        images.clear();
        fallenBack.clear();
        asked.clear();
        latest.clear();
    }

    return { draw, forget, remove };
}
