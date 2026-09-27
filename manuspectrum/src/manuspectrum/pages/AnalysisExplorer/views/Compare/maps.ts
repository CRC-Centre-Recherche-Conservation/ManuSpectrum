import type {
    FileEntry,
    FileLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

export type LayerKind = FileLayer["kind"];

/** One layer of the maps compared side by side: the same element, band or named layer in each map. */
export interface SharedLayer {
    id: string;
    label: string;
    kind: LayerKind;
}

const KIND_ORDER: Record<LayerKind, number> = {
    element: 0,
    band: 1,
    other: 2,
};

/** What makes two layers of different maps the same: the element symbol, the band's value and unit, else the label. */
export function layerIdOf(layer: FileLayer): string {
    if (layer.kind === "element" && layer.element) {
        return `element:${layer.element}`;
    }
    if (layer.kind === "band" && layer.band) {
        return `band:${layer.band.value} ${layer.band.unit}`;
    }
    return `other:${layer.label}`;
}

/**
 * Every layer of `maps`, once: the elements in the order the manifests give
 * them (slot order), then the bands by unit and value (D46), then the other
 * layers in the order met.
 */
export function sharedLayers(maps: readonly MapLine[]): SharedLayer[] {
    const met = new Map<string, SharedLayer & { band: FileLayer["band"] }>();
    for (const line of maps) {
        for (const layer of line.file.layers) {
            const id = layerIdOf(layer);
            if (!met.has(id)) {
                met.set(id, {
                    id,
                    label: layer.label,
                    kind: id.startsWith("other:") ? "other" : layer.kind,
                    band: id.startsWith("band:") ? layer.band : null,
                });
            }
        }
    }
    return [...met.values()]
        .sort((a, b) => {
            if (a.kind !== b.kind) {
                return KIND_ORDER[a.kind] - KIND_ORDER[b.kind];
            }
            if (a.band && b.band) {
                return (
                    a.band.unit.localeCompare(b.band.unit) ||
                    a.band.value - b.band.value
                );
            }
            return 0;
        })
        .map(({ id, label, kind }) => ({ id, label, kind }));
}

/** The layer of `file` that is shared layer `id`; null when the map lacks it. */
export function layerIn(file: FileEntry, id: string | null): FileLayer | null {
    if (id === null) return null;
    return file.layers.find((layer) => layerIdOf(layer) === id) ?? null;
}

/** The kind that names the shared layers: theirs when they all share it, else plain layers. */
export function sharedKind(layers: readonly SharedLayer[]): LayerKind {
    const kinds = new Set(layers.map((layer) => layer.kind));
    return kinds.size === 1 ? [...kinds][0] : "other";
}

/** The position in `layers` to open on: the layer the first one-layer key (`im:`) names, else the first. */
export function startLayer(
    maps: readonly MapLine[],
    layers: readonly SharedLayer[],
): number {
    for (const line of maps) {
        const named = line.file.layers.find(
            (layer) => layer.index === line.named,
        );
        if (named) {
            const position = layers.findIndex(
                (layer) => layer.id === layerIdOf(named),
            );
            if (position >= 0) return position;
        }
    }
    return 0;
}
