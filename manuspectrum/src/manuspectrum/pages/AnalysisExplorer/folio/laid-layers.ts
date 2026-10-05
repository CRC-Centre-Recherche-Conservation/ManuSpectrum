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
 * `curtainLabel`. A layer whose image does not load is tried once more at
 * `fallbackUrl`; `failed` is called with the key only once
 * that fallback has also failed, or had none to try.
 */
export function laidLayers(
    map: L.Map,
    options: { curtainLabel: string; failed: (key: string) => void },
): LaidLayers {
    const images = new Map<string, L.ImageOverlay>();
    /** Keys whose layer already fell back to `fallbackUrl` once. */
    const fallenBack = new Set<string>();
    let sideBySide: L.SideBySide | null = null;

    function onError(overlay: FolioOverlay): void {
        const layer = images.get(overlay.key);
        if (
            layer &&
            !fallenBack.has(overlay.key) &&
            overlay.fallbackUrl &&
            overlay.fallbackUrl !== overlay.url
        ) {
            fallenBack.add(overlay.key);
            layer.setUrl(overlay.fallbackUrl);
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
            }
        }
        for (const overlay of overlays) {
            const existing = images.get(overlay.key);
            if (existing) {
                existing.setOpacity(overlay.opacity);
                existing.setBounds(L.latLngBounds(overlay.bounds));
            } else {
                const pane = overlayPane(map, overlay.key);
                const layer = L.imageOverlay(overlay.url, overlay.bounds, {
                    opacity: overlay.opacity,
                    className: "folio-overlay",
                    alt: overlay.label,
                    pane,
                });
                layer.on("error", () => onError(overlay));
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
        }
    }

    function remove(): void {
        sideBySide?.remove();
        sideBySide = null;
        images.clear();
        fallenBack.clear();
    }

    return { draw, forget, remove };
}
