import L from "leaflet";
import { imageUrl } from "utils/iiif-image";

import { shapeBounds } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";

import type {
    AnalysisPayload,
    Annotation,
    ImageRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LatLng } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import type { Overlay } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const OVERLAY_SIZE = 2048;

export interface FolioOverlay {
    key: string;
    url: string;
    bounds: [LatLng, LatLng];
    opacity: number;
    label: string;
}

/** The key of a layer's settings in `store.overlays`. */
export function overlayKey(analysisId: string, index: number): string {
    return `${analysisId}:${index}`;
}

/** The layer image: its own URL, else the IIIF image service at most `size` px on a side. */
export function layerImageUrl(
    image: ImageRef,
    size = OVERLAY_SIZE,
): string | null {
    if (image.url) return image.url;
    if (image.service) {
        return imageUrl(image.service, { size: `!${size},${size}` });
    }
    return null;
}

/**
 * The imaging layers of the open analysis that are switched on, each stretched
 * into the bounding box of the analysis zone on this page (indicative, not
 * registered). An analysis with only a point here lays nothing.
 */
export function folioOverlays(
    analysis: AnalysisPayload | null,
    overlays: Record<string, Overlay>,
    annotations: readonly Annotation[],
): FolioOverlay[] {
    if (!analysis) return [];
    const zone = annotations.find(
        (entry) =>
            entry.analysis === analysis.id && shapeBounds(entry.shape) !== null,
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
                    bounds,
                    opacity: setting.opacity,
                    label: layer.label,
                });
            }
        }
    }
    return result;
}

/** leaflet-side-by-side clips `layer.getContainer()`; an image overlay's container is its `<img>`. */
export function curtainable(layer: L.ImageOverlay): L.ImageOverlay {
    (
        layer as L.ImageOverlay & {
            getContainer?: () => HTMLElement | undefined;
        }
    ).getContainer = () => layer.getElement();
    return layer;
}
