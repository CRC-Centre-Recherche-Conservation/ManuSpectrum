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

/** Zoom levels the reader may go past the zoom at which a layer shows one image pixel per screen pixel. */
export const OVERZOOM_LEVELS = 3;

/**
 * Lets the reader zoom `OVERZOOM_LEVELS` past `nativeZoom` on `map`. leaflet-iiif
 * 3.0.0 sets the map's `_layersMaxZoom` to the layer's own `maxNativeZoom`
 * (0 for an image of one tile), which is the map's maximum while its
 * `maxZoom` option is unset: an image served at 236 px could not be shown
 * larger than 236 px. An explicit `maxZoom` takes precedence over it; the
 * layers are still never asked for tiles beyond `maxNativeZoom`, Leaflet
 * scales the tiles it has.
 */
export function allowOverzoom(map: L.Map, nativeZoom: number): void {
    const limit = nativeZoom + OVERZOOM_LEVELS;
    if (map.options.maxZoom !== limit) map.setMaxZoom(limit);
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

/** A size in image pixels. */
interface PixelSize {
    w: number;
    h: number;
}

/** A shift in image pixels at the group's pixel scale, y downwards. */
export interface PixelOffset {
    x: number;
    y: number;
}

/** A layer taken into a `ScaleGroup`. */
export interface ScaleMember {
    /** The size the layer is served at, in image pixels. */
    size: PixelSize;
    /**
     * The map zoom at which the layer shows one image pixel per screen pixel
     * when it is drawn alone (leaflet-iiif's `maxNativeZoom`); null for a
     * layer that follows any zoom (a plain image).
     */
    nativeZoom: number | null;
    /**
     * Draws the layer so that one image pixel is one screen pixel at map zoom
     * `zoom`, its top-left corner `offset` image pixels from the frame's.
     */
    apply: (zoom: number, offset: PixelOffset) => void;
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
 *
 * The layers are centred in the group's frame, the box of the widest and the
 * tallest of them (`frame`), so a smaller canvas sits in the middle of the
 * largest one, at the same pixel scale and never stretched; each member is
 * told its offset in image pixels from the frame's top-left corner, which is
 * the map's origin. How a leaflet-iiif layer is moved is in `shiftTiles`.
 */
export interface ScaleGroup {
    join: (member: ScaleMember) => void;
    leave: (member: ScaleMember) => void;
    /** The map zoom at which every layer of the group shows one image pixel per screen pixel. */
    zoom: () => number;
    /** The box that holds every layer, in image pixels at the group's scale; null while the group is empty. */
    frame: () => PixelSize | null;
}

/**
 * A scale group; `changed` is called with the zoom when joining or leaving
 * moves the zoom or the frame.
 */
export function createScaleGroup(changed?: (zoom: number) => void): ScaleGroup {
    const members: ScaleMember[] = [];
    let current: number | null = null;
    let box: PixelSize | null = null;

    function target(): number {
        const own = members.flatMap((member) =>
            member.nativeZoom === null ? [] : [member.nativeZoom],
        );
        return own.length ? Math.min(...own) : 0;
    }

    function frameOf(): PixelSize | null {
        if (!members.length) return null;
        return {
            w: Math.max(...members.map((member) => member.size.w)),
            h: Math.max(...members.map((member) => member.size.h)),
        };
    }

    function place(member: ScaleMember, zoom: number): void {
        const frame = box as PixelSize;
        member.apply(zoom, {
            x: (frame.w - member.size.w) / 2,
            y: (frame.h - member.size.h) / 2,
        });
    }

    function settle(added?: ScaleMember): void {
        const next = target();
        const frame = frameOf();
        const same =
            next === current && frame?.w === box?.w && frame?.h === box?.h;
        const before = current;
        current = next;
        box = frame;
        if (same) {
            if (added) place(added, next);
            return;
        }
        for (const member of members) place(member, next);
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
            else {
                current = null;
                box = null;
            }
        },
        zoom: () => current ?? 0,
        frame: () => box,
    };
}

/**
 * Moves the tiles of a leaflet-iiif layer by a pixel offset without moving
 * its map pane (leaflet-side-by-side clips the pane, so a pane moved by CSS
 * would carry the divider with it). Leaflet 1.6 places a tile at
 * `coords * tileSize - level.origin` and loads the tiles that cover the
 * viewport; the layer's image is shifted by `offset` image pixels (at the
 * group's zoom `zoom`, so `offset * 2^(z - zoom)` map pixels at the tile zoom
 * `z`, whole pixels so that the tiles keep touching) by adding that shift to
 * `_getTilePos`, and the viewport the layer loads for is shifted back by
 * the same amount in `_getTiledPixelBounds`, so the tiles that are asked are
 * the ones under the screen after the shift. Nothing else moves: the map's
 * CRS, the clip and the clicks stay in the map's own coordinates. `set`
 * tells whether the shift changed.
 */
function shiftTiles(layer: IiifLayer): {
    set: (zoom: number, offset: PixelOffset) => boolean;
} {
    let groupZoom = 0;
    let offset: PixelOffset = { x: 0, y: 0 };
    function pixelsAt(tileZoom: number): L.Point {
        const factor = 2 ** (tileZoom - groupZoom);
        return L.point(
            Math.round(offset.x * factor),
            Math.round(offset.y * factor),
        );
    }
    const raw = layer as unknown as {
        _getTilePos?: (coords: L.Coords) => L.Point;
        _getTiledPixelBounds?: (center: L.LatLng) => L.Bounds;
        _tileZoom?: number;
    };
    const getTilePos = raw._getTilePos;
    if (getTilePos) {
        raw._getTilePos = (coords) =>
            getTilePos.call(layer, coords).add(pixelsAt(coords.z));
    }
    const getBounds = raw._getTiledPixelBounds;
    if (getBounds) {
        raw._getTiledPixelBounds = (center) => {
            const bounds = getBounds.call(layer, center);
            const shift = pixelsAt(raw._tileZoom ?? 0);
            return L.bounds(
                bounds.min?.subtract(shift) as L.Point,
                bounds.max?.subtract(shift) as L.Point,
            );
        };
    }
    return {
        set(zoom, next) {
            const moved =
                zoom !== groupZoom ||
                next.x !== offset.x ||
                next.y !== offset.y;
            groupZoom = zoom;
            offset = next;
            return moved;
        },
    };
}

/** The scale member of a leaflet-iiif layer whose info.json is read. */
function iiifMember(
    map: L.Map,
    layer: IiifLayer,
    size: PixelSize,
): ScaleMember {
    const own = nativeZoomOf({ layer, remove: () => undefined });
    const shift = shiftTiles(layer);
    return {
        nativeZoom: own,
        size,
        apply(zoom, offset) {
            const zoomOffset = own - zoom;
            allowOverzoom(map, zoom);
            const moved = shift.set(zoom, offset);
            if (
                !moved &&
                layer.options.zoomOffset === zoomOffset &&
                layer.options.maxNativeZoom === zoom
            ) {
                return;
            }
            layer.options.zoomOffset = zoomOffset;
            layer.options.maxNativeZoom = zoom;
            if (layer._container && map.hasLayer(layer)) {
                // Leaflet 1.6 keeps a stale tile zoom within one level of the
                // map's; a view reset recomputes it. Tiles already placed
                // keep their old position until they are drawn again.
                layer._resetView();
                if (moved) layer.redraw();
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
            member = iiifMember(map, laid.layer as IiifLayer, size);
            options.scale.join(member);
        }
        const zoom = options.scale ? options.scale.zoom() : nativeZoomOf(laid);
        allowOverzoom(map, zoom);
        handlers.read(size, zoom);
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

/** The bounds of an image of `size` pixels, one pixel per unit at map zoom `zoom`, `offset` pixels from the origin. */
function imageBounds(
    map: L.Map,
    size: { w: number; h: number },
    zoom: number,
    offset: PixelOffset = { x: 0, y: 0 },
): L.LatLngBounds {
    return L.latLngBounds(
        map.unproject([offset.x, offset.y + size.h], zoom),
        map.unproject([offset.x + size.w, offset.y], zoom),
    );
}

/**
 * Lays a layer's image on `map` at the size it is served at, anchored at the
 * origin or, in a `scale` group, centred in the group's frame: through its IIIF image service (`layServed`), else through its
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
                    size,
                    apply: (zoom, offset) => {
                        allowOverzoom(map, zoom);
                        laid.setBounds(imageBounds(map, size, zoom, offset));
                    },
                };
                options.scale.join(member);
            } else allowOverzoom(map, 0);
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
