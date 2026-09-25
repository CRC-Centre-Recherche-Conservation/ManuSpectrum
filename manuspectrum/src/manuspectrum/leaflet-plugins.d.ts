// leaflet-side-by-side 2.1.0 (vendored by Arches under the alias
// `leaflet-side-by-side`) registers `L.control.sideBySide` on import.
import "leaflet";

declare module "leaflet" {
    interface SideBySide extends Control {
        setLeftLayers(layers: Layer | Layer[]): this;
        setRightLayers(layers: Layer | Layer[]): this;
        getPosition(): number;
        // The control includes L.Evented: `leftlayeradd`, `rightlayerremove`, `dividermove`…
        on(
            type: string,
            handler: LeafletEventHandlerFn,
            context?: unknown,
        ): this;
    }
    namespace control {
        function sideBySide(
            left: Layer | Layer[],
            right: Layer | Layer[],
        ): SideBySide;
    }
    namespace TileLayer {
        function iiif(
            url: string,
            options?: TileLayerOptions & {
                fitBounds?: boolean;
                setMaxBounds?: boolean;
                quality?: string;
            },
        ): TileLayer;
    }
    namespace tileLayer {
        function iiif(
            url: string,
            options?: TileLayerOptions & {
                fitBounds?: boolean;
                setMaxBounds?: boolean;
                quality?: string;
            },
        ): TileLayer;
    }
}

declare module "leaflet-side-by-side";
