import L from "leaflet";
import "leaflet-iiif";
import { infoJsonUrl } from "utils/iiif-image";

/** The leaflet-iiif 3.0.0 state read here: the info.json request, the image sizes it yields, the tile container. */
type IiifLayer = L.TileLayer & {
    _infoPromise?: Promise<unknown> | null;
    _imageSizes?: unknown[];
    _container?: HTMLElement;
};

/** A page image on its way to a map; `remove` takes it off, laid or not. */
export interface PageLayer {
    layer: L.TileLayer;
    remove: () => void;
}

/**
 * Lays the IIIF image `service` on `map` once leaflet-iiif has read its
 * info.json, unless `remove` was called first. leaflet-iiif lays its tiles
 * only after that read (never, when the image host refuses it), and
 * GridLayer.onRemove throws on a layer whose tiles are not laid: an unread
 * page never reaches the map, and a page removed in the instant between its
 * addition and its tiles is dropped without calling GridLayer.onRemove.
 * `failed` is called when the info.json cannot be read.
 */
export function layPage(
    map: L.Map,
    service: string,
    failed: () => void,
): PageLayer {
    const layer = L.tileLayer.iiif(infoJsonUrl(service), {
        fitBounds: true,
        setMaxBounds: false,
    }) as IiifLayer;
    const onRemove = layer.onRemove;
    layer.onRemove = (from: L.Map) =>
        layer._container ? onRemove.call(layer, from) : layer;
    let removed = false;
    void Promise.resolve(layer._infoPromise).then(
        () => {
            if (removed) return;
            if (layer._imageSizes) map.addLayer(layer);
            else failed();
        },
        () => {
            if (!removed) failed();
        },
    );
    return {
        layer,
        remove: () => {
            removed = true;
            if (map.hasLayer(layer)) map.removeLayer(layer);
        },
    };
}

/** Fits the whole image of a laid page (leaflet-iiif's private `_fitBounds`); false when the page is not on the map. */
export function fitPage(map: L.Map, page: PageLayer | null): boolean {
    const layer = page?.layer;
    if (!layer || !map.hasLayer(layer) || !("_fitBounds" in layer)) {
        return false;
    }
    (layer as unknown as { _fitBounds: () => void })._fitBounds();
    return true;
}
