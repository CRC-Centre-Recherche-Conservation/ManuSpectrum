import L from "leaflet";
import "leaflet-iiif";
import { infoJsonUrl } from "utils/iiif-image";

import {
    curtainable,
    layerImageChain,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";

import type { ImageRef } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** The leaflet-iiif 3.0.0 state read here: the info.json request, the image sizes it yields, the tile container. */
type IiifLayer = L.TileLayer & {
    _infoPromise?: Promise<unknown> | null;
    _imageSizes?: unknown[];
    _container?: HTMLElement;
    maxNativeZoom?: number;
    _resetView: () => void;
    _isValidTile: (coords: L.Coords) => boolean;
    _getZoomForUrl: () => number;
    /** The image's size in pixels, read from its info.json. */
    x?: number;
    y?: number;
    _setView: (
        center: L.LatLng,
        zoom: number,
        noPrune?: boolean,
        noUpdate?: boolean,
    ) => void;
};

/**
 * Whether the region of a tile starts inside the image. leaflet-iiif 3.0.0
 * accepts every tile at a negative zoom, so a view below the image's own
 * levels asks for regions that begin past its edge, which the image server
 * refuses.
 */
function startsInside(layer: IiifLayer, coords: L.Coords): boolean {
    if (layer.x === undefined || layer.y === undefined) return true;
    const side =
        (layer.options.tileSize as number) *
        2 ** ((layer.maxNativeZoom ?? 0) - layer._getZoomForUrl());
    return coords.x * side < layer.x && coords.y * side < layer.y;
}

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
 * leaflet-iiif lays its tile container in a promise callback, after
 * `map.addLayer` returned and the layer listens to the map's view events;
 * `GridLayer._setView` throws on a layer whose container is not laid, so a
 * view set in that interval is left to the layer's own `onAdd`, which reads
 * the map's view once the container exists. leaflet-iiif then sets the
 * layer's `minZoom` to the zoom at which the image fits the map as it is at
 * that moment, and Leaflet drops every tile of a map zoomed below it; a caller
 * that owns the view (`fitBounds` false) has its map limit the zoom, so the
 * layer is given no minimum, and reads the view again. `failed` is called when the
 * info.json cannot be read. The view fits the
 * whole page once laid, unless `fitBounds` is false (the caller keeps it).
 * With `pane`, the tiles go in that map pane (`overlayPane`).
 */
export function layPage(
    map: L.Map,
    service: string,
    failed: () => void,
    { fitBounds = true, pane }: { fitBounds?: boolean; pane?: string } = {},
): PageLayer {
    const layer = L.tileLayer.iiif(infoJsonUrl(service), {
        fitBounds,
        setMaxBounds: false,
        ...(pane ? { pane } : {}),
    }) as IiifLayer;
    const setView = layer._setView;
    layer._setView = function (...args: Parameters<typeof setView>) {
        if (layer._container) setView.apply(layer, args);
    };
    const isValidTile = layer._isValidTile;
    layer._isValidTile = (coords: L.Coords) =>
        isValidTile.call(layer, coords) && startsInside(layer, coords);
    const onRemove = layer.onRemove;
    layer.onRemove = (from: L.Map) =>
        layer._container ? onRemove.call(layer, from) : layer;
    let removed = false;
    void Promise.resolve(layer._infoPromise).then(
        () => {
            if (removed) return;
            if (layer._imageSizes) {
                map.addLayer(layer);
                void Promise.all([layer._infoPromise]).then(() => {
                    if (!removed && layer._container && map.hasLayer(layer)) {
                        if (!fitBounds) layer.options.minZoom = -Infinity;
                        layer._resetView();
                    }
                });
            } else failed();
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

/** A layer taken into a `ScaleGroup`. */
export interface ScaleMember {
    /**
     * The map zoom at which the layer shows one image pixel per screen pixel
     * when it is drawn alone (leaflet-iiif's `maxNativeZoom`); null for a
     * layer that follows any zoom (a plain image).
     */
    nativeZoom: number | null;
    /** Draws the layer so that one image pixel is one screen pixel at map zoom `zoom`. */
    apply: (zoom: number) => void;
}

/**
 * The layers of one map drawn pixel for pixel: every layer keeps its own
 * pixel scale relative to the others.
 *
 * leaflet-iiif 3.0.0 places an image at `size / 2^maxNativeZoom` CRS units,
 * `maxNativeZoom` being `ceil(log2(max(w, h) / tileSize))`: two images in
 * different power-of-two buckets would be drawn with a factor of two between
 * their scales. The group's `zoom` is the lowest `maxNativeZoom` of its
 * layers; each leaflet-iiif layer is given `zoomOffset = own - zoom` (its
 * tiles are asked at the zoom `z + zoomOffset`, so that a tile, still placed
 * at the map zoom `z`, covers `tileSize * 2^(own - z - offset)` source
 * pixels) and `maxNativeZoom = zoom` (the tiles are not asked beyond the
 * zoom at which one image pixel is one screen pixel). Every layer then
 * spans `size / 2^zoom` units and shows one image pixel per screen pixel at
 * `zoom`. A plain image is simply laid at `size / 2^zoom` units.
 */
export interface ScaleGroup {
    join: (member: ScaleMember) => void;
    leave: (member: ScaleMember) => void;
    /** The map zoom at which every layer of the group shows one image pixel per screen pixel. */
    zoom: () => number;
}

/** A scale group; `changed` is called with the new zoom when joining or leaving moves it. */
export function createScaleGroup(changed?: (zoom: number) => void): ScaleGroup {
    const members: ScaleMember[] = [];
    let current: number | null = null;

    function target(): number {
        const own = members.flatMap((member) =>
            member.nativeZoom === null ? [] : [member.nativeZoom],
        );
        return own.length ? Math.min(...own) : 0;
    }

    function settle(added?: ScaleMember): void {
        const next = target();
        if (next === current) {
            added?.apply(next);
            return;
        }
        const before = current;
        current = next;
        for (const member of members) member.apply(next);
        if (before !== null) changed?.(next);
    }

    return {
        join(member) {
            members.push(member);
            settle(member);
        },
        leave(member) {
            const index = members.indexOf(member);
            if (index < 0) return;
            members.splice(index, 1);
            if (members.length) settle();
            else current = null;
        },
        zoom: () => current ?? 0,
    };
}

/** The scale member of a leaflet-iiif layer whose info.json is read. */
function iiifMember(map: L.Map, layer: IiifLayer): ScaleMember {
    const own = nativeZoomOf({ layer, remove: () => undefined });
    return {
        nativeZoom: own,
        apply(zoom) {
            const offset = own - zoom;
            if (
                layer.options.zoomOffset === offset &&
                layer.options.maxNativeZoom === zoom
            ) {
                return;
            }
            layer.options.zoomOffset = offset;
            layer.options.maxNativeZoom = zoom;
            if (layer._container && map.hasLayer(layer)) {
                // Leaflet 1.6 keeps a stale tile zoom within one level of the
                // map's; a view reset recomputes it.
                layer._resetView();
            }
        },
    };
}

/**
 * `layPage` that does not fit the view and reports the page once it is on the
 * map: `read` with the size its service serves and the zoom at which that size
 * is one pixel per unit (the `scale` group's, when given), or `failed` when
 * the info.json is refused or holds no size. Nothing is reported for a page
 * removed first. In a `scale` group the page is drawn at the group's common
 * pixel scale (`ScaleGroup`).
 */
export function layServed(
    map: L.Map,
    service: string,
    handlers: {
        read: (size: { w: number; h: number }, nativeZoom: number) => void;
        failed: () => void;
    },
    options: { pane?: string; scale?: ScaleGroup } = {},
): PageLayer {
    const laid = layPage(map, service, handlers.failed, {
        fitBounds: false,
        ...(options.pane ? { pane: options.pane } : {}),
    });
    let member: ScaleMember | null = null;
    function onAdd(event: L.LayerEvent): void {
        if (event.layer !== laid.layer) return;
        map.off("layeradd", onAdd);
        const size = servedSize(laid);
        if (!size) {
            handlers.failed();
            return;
        }
        if (options.scale) {
            member = iiifMember(map, laid.layer as IiifLayer);
            options.scale.join(member);
        }
        handlers.read(
            size,
            options.scale ? options.scale.zoom() : nativeZoomOf(laid),
        );
    }
    map.on("layeradd", onAdd);
    return {
        layer: laid.layer,
        remove: () => {
            map.off("layeradd", onAdd);
            if (member) options.scale?.leave(member);
            member = null;
            laid.remove();
        },
    };
}

/** An image laid on a map; `remove` takes it off, laid or not. */
export interface LaidImage {
    remove: () => void;
}

/** The bounds of an image of `size` pixels, one pixel per unit at map zoom `zoom`, anchored at the origin. */
function imageBounds(
    map: L.Map,
    size: { w: number; h: number },
    zoom: number,
): L.LatLngBounds {
    return L.latLngBounds(
        map.unproject([0, size.h], zoom),
        map.unproject([size.w, 0], zoom),
    );
}

/**
 * Lays a layer's image on `map`, anchored at the origin, at the size it is
 * served at: through its IIIF image service (`layServed`), else through its
 * own URL as an image overlay at its natural size, trying the addresses of
 * `layerImageChain` in turn. `read` is called once it is on the map with its
 * size, the zoom at which that size is one pixel per unit (the `scale`
 * group's, when given) and the Leaflet layer; `failed` when no address
 * answers. With `pane` the image is drawn in that map pane; with `curtain`
 * the layer answers `getContainer()` with that pane so that
 * leaflet-side-by-side clips it (`curtainable`). In a `scale` group every
 * image keeps its own pixel scale relative to the others (`ScaleGroup`).
 */
export function layImage(
    map: L.Map,
    image: ImageRef,
    handlers: {
        read: (
            size: { w: number; h: number },
            nativeZoom: number,
            layer: L.Layer,
        ) => void;
        failed: () => void;
    },
    options: { pane?: string; scale?: ScaleGroup; curtain?: boolean } = {},
): LaidImage {
    const paneElement = options.pane ? map.getPane(options.pane) : undefined;
    function wrap<T extends L.Layer>(layer: T): T {
        return options.curtain && paneElement
            ? curtainable(layer, paneElement)
            : layer;
    }
    if (image.service) {
        let page: PageLayer | null = null;
        page = layServed(
            map,
            image.service,
            {
                read: (size, zoom) =>
                    handlers.read(size, zoom, (page as PageLayer).layer),
                failed: handlers.failed,
            },
            { pane: options.pane, scale: options.scale },
        );
        wrap(page.layer);
        return { remove: () => page?.remove() };
    }
    const addresses = layerImageChain(image);
    let removed = false;
    let overlay: L.ImageOverlay | null = null;
    let member: ScaleMember | null = null;
    function tryNext(): void {
        const url = addresses.shift();
        if (removed) return;
        if (!url) {
            handlers.failed();
            return;
        }
        const probe = new Image();
        probe.onload = () => {
            if (removed) return;
            const size = { w: probe.naturalWidth, h: probe.naturalHeight };
            const laid = L.imageOverlay(
                url,
                imageBounds(map, size, options.scale?.zoom() ?? 0),
                options.pane ? { pane: options.pane } : {},
            );
            overlay = wrap(laid);
            overlay.addTo(map);
            if (options.scale) {
                member = {
                    nativeZoom: null,
                    apply: (zoom) =>
                        laid.setBounds(imageBounds(map, size, zoom)),
                };
                options.scale.join(member);
            }
            handlers.read(size, options.scale?.zoom() ?? 0, laid);
        };
        probe.onerror = tryNext;
        probe.src = url;
    }
    tryNext();
    return {
        remove: () => {
            removed = true;
            if (member) options.scale?.leave(member);
            member = null;
            overlay?.remove();
            overlay = null;
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

/** The size of a page as its image service serves it (the largest of the info.json's), in pixels; null until the info.json is read. */
export function servedSize(
    page: PageLayer | null,
): { w: number; h: number } | null {
    const sizes = (page?.layer as IiifLayer | undefined)?._imageSizes as
        | { x?: number; y?: number }[]
        | undefined;
    const largest = sizes?.[sizes.length - 1];
    if (
        !largest ||
        !Number.isFinite(largest.x) ||
        !Number.isFinite(largest.y)
    ) {
        return null;
    }
    return { w: largest.x as number, h: largest.y as number };
}

/** The map zoom at which the page shows at its served size, one pixel per unit. */
export function nativeZoomOf(page: PageLayer | null): number {
    const layer = page?.layer as IiifLayer | undefined;
    const declared = layer?.options?.maxNativeZoom;
    if (typeof declared === "number") return declared;
    return Math.max(0, (layer?._imageSizes?.length ?? 1) - 1);
}
