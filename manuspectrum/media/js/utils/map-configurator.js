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
 * Remove this file at Arches 8.2, whose map view model has no Mapbox geocoder.
 * After adding or deleting a shadow, stop `npm start`, delete
 * `node_modules/.cache/webpack` and start again.
 */
import arches from 'arches';
import MapboxGeocoder from 'mapbox-gl-geocoder';

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
    },
};

export default mapConfigurator;
