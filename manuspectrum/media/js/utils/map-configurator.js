/*
 * Shadows arches/app/media/js/utils/map-configurator.js (Arches 8.1.5), the
 * project hook that `viewmodels/map.js` calls at the start and at the end of the
 * map `load` handler. The core file is two empty functions.
 *
 * Difference: without a Mapbox key (the OpenFreeMap basemap needs none) the
 * `MapboxGeocoder` control that `viewmodels/map.js` adds in that handler is
 * skipped, because its `onAdd` throws without an access token and stops the
 * rest of the handler (popups, hover, draw mode). `preConfig` makes
 * `map.addControl` ignore a MapboxGeocoder, `postConfig` puts it back.
 *
 * `postConfig` also follows the page language on the OpenFreeMap labels: on a
 * French page every symbol layer whose `text-field` reads a name falls back
 * from `name:fr` to the style's own expression (English name, then local name).
 * The style stays as the vendored JSON; nothing is fetched again. The core view
 * models call `map.setStyle(style)` again when the layers change, which brings
 * the vendored labels back: `postConfig` also installs an own `setStyle` that
 * rewrites the labels (French page) and adds the missing fonts (below) of the
 * style it is given, then calls the map's own method.
 *
 * Both also give a font to every symbol layer that has a `text-field` and no
 * `text-font` (any page language, any source): the Arches resource layers
 * (`geojson_feature_collection_layer_template.txt`, the cluster count label)
 * declare none, and MapLibre then asks the glyph server for its Mapbox default
 * stack, "Open Sans Regular, Arial Unicode MS Regular", which OpenFreeMap does
 * not serve (404). The font is one the basemap style itself uses.
 *
 * Remove this file at Arches 8.2, whose map view model has no Mapbox geocoder.
 * After adding or deleting a shadow, stop `npm start`, delete
 * `node_modules/.cache/webpack` and start again.
 */
import arches from "arches";
import MapboxGeocoder from "mapbox-gl-geocoder";

const BASEMAP_SOURCE = "openfreemap";

const FALLBACK_FONT = ["Noto Sans Regular"];

const readsName = (expression) => {
    if (!Array.isArray(expression)) return false;
    if (expression[0] === "get")
        return /^name(_en|:latin)?$/.test(expression[1]);
    return expression.some(readsName);
};

const isFrench = (expression) =>
    Array.isArray(expression) &&
    expression[0] === "coalesce" &&
    Array.isArray(expression[1]) &&
    expression[1][0] === "get" &&
    expression[1][1] === "name:fr";

/**
 * The `text-field` a basemap label layer takes for a page language: on a French
 * page `name:fr` first, then the layer's current expression (formatting kept);
 * any other language, or an expression that reads no name, is returned as is.
 */
export const labelField = (language, current) => {
    if (
        !String(language || "")
            .toLowerCase()
            .startsWith("fr")
    )
        return current;
    if (isFrench(current)) return current;
    if (!readsName(current)) return current;
    return ["coalesce", ["get", "name:fr"], current];
};

const isFrenchPage = () =>
    String(arches.activeLanguage || "")
        .toLowerCase()
        .startsWith("fr");

const needsFont = (layer) =>
    layer.type === "symbol" &&
    layer.layout &&
    layer.layout["text-field"] !== undefined &&
    layer.layout["text-font"] === undefined;

const localizeLayer = (layer) => {
    if (layer.type !== "symbol" || layer.source !== BASEMAP_SOURCE)
        return layer;
    const current = layer.layout && layer.layout["text-field"];
    const next = labelField(arches.activeLanguage, current);
    if (next === current) return layer;
    return { ...layer, layout: { ...layer.layout, "text-field": next } };
};

const withFont = (layer) =>
    needsFont(layer)
        ? {
              ...layer,
              layout: { ...layer.layout, "text-font": FALLBACK_FONT },
          }
        : layer;

const adaptLayer = (layer) => withFont(localizeLayer(layer));

const adaptLayers = (map) => {
    const style = map.getStyle();
    if (!style || !Array.isArray(style.layers)) return;
    style.layers.forEach((layer) => {
        if (needsFont(layer))
            map.setLayoutProperty(layer.id, "text-font", FALLBACK_FONT);
        if (!isFrenchPage()) return;
        const localized = localizeLayer(layer);
        if (localized !== layer)
            map.setLayoutProperty(
                layer.id,
                "text-field",
                localized.layout["text-field"],
            );
    });
};

const adaptOnSetStyle = (map) => {
    const setStyle = map.setStyle;
    map.setStyle = function (style, options) {
        if (style && typeof style === "object" && Array.isArray(style.layers))
            style = { ...style, layers: style.layers.map(adaptLayer) };
        return setStyle.call(this, style, options);
    };
};

const mapConfigurator = {
    preConfig: function (map) {
        if (arches.mapboxApiKey) return;
        const addControl = map.addControl;
        map.addControl = function (control, position) {
            if (control instanceof MapboxGeocoder) return this;
            return addControl.call(this, control, position);
        };
    },
    postConfig: function (map) {
        delete map.addControl;
        adaptLayers(map);
        adaptOnSetStyle(map);
    },
};

export default mapConfigurator;
