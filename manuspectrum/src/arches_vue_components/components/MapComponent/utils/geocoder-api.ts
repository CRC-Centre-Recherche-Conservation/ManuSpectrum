/*
 * Shadows arches_vue_components/components/MapComponent/utils/geocoder-api.ts
 * (Arches 8.2.0), the project override point the release notes name for the
 * Vue map's geocoder.
 *
 * Difference: the core file queries OpenStreetMap Nominatim; the back office
 * uses no third-party geocoder, so this one answers without a request and the
 * attribution is empty. The search box of the map stays, with no result.
 */
import type {
    MaplibreGeocoderApi,
    MaplibreGeocoderFeatureResults,
} from "@maplibre/maplibre-gl-geocoder";

export const GEOCODER_ATTRIBUTION = "";

async function forwardGeocode(): Promise<MaplibreGeocoderFeatureResults> {
    return { type: "FeatureCollection", features: [] };
}

export const geocoderApi: MaplibreGeocoderApi = { forwardGeocode };
