/**
 * Shadow of arches/app/media/js/views/components/iiif-viewer.js (Arches 8.1.4).
 *
 * Wrapper, no core code copied: the core module is imported through the
 * `arches/arches/app` alias (webpack.common.js) and applied as is.
 *
 * Diff vs original:
 *   - `params.onEachFeature` defaults to the summary popup binder, so the
 *     read-only annotation layer of every host (annotation widget, image
 *     service manager, manifest widget) opens the fiche instead of the core
 *     popup; a handler passed by the host wins
 *   - annotations are restacked largest first once drawn, so a large
 *     annotation no longer covers the smaller ones inside it and takes their
 *     clicks (`stackSmallestOnTop`)
 *   - the 'iiif-viewer' Knockout component is re-registered on the wrapper
 *   - imports `views/components/ms-summary-popup`, which registers the
 *     'ms-summary-popup' component the binder mounts
 */
import ko from 'knockout';
import L from 'leaflet';
import CoreIIIFViewerViewmodel from 'arches/arches/app/media/js/views/components/iiif-viewer';
import iiifViewerTemplate from 'templates/views/components/iiif-viewer.htm';
import { bindLeafletSummaryPopup } from 'utils/summary-popup';
import 'views/components/ms-summary-popup';

/** Bounding-box area of a vector layer in degrees²; markers count as 0. */
function footprint(layer) {
    if (typeof layer.getBounds !== 'function') return 0;
    const bounds = layer.getBounds();
    if (!bounds.isValid()) return 0;
    const sw = bounds.getSouthWest();
    const ne = bounds.getNorthEast();
    return Math.abs((ne.lat - sw.lat) * (ne.lng - sw.lng));
}

/**
 * Leaflet keeps annotations in manifest order, and a click reaches only the
 * topmost path. After each batch of additions, every annotation path is
 * brought to the front from the largest to the smallest.
 */
export function stackSmallestOnTop(map, schedule = (fn) => setTimeout(fn, 0)) {
    let pending = false;
    map.on('layeradd', (event) => {
        if (pending || !(event.layer instanceof L.Path) || !event.layer.feature) return;
        pending = true;
        schedule(() => {
            pending = false;
            const paths = [];
            map.eachLayer((layer) => {
                if (layer instanceof L.Path && layer.feature) paths.push(layer);
            });
            paths.sort((a, b) => footprint(b) - footprint(a));
            paths.forEach((layer) => layer.bringToFront());
        });
    });
}

const IIIFViewerViewmodel = function(params) {
    if (params && !params.onEachFeature) {
        params.onEachFeature = bindLeafletSummaryPopup;
    }
    CoreIIIFViewerViewmodel.apply(this, [params]);

    if (ko.isObservable(this.map)) {
        const mapSubscription = this.map.subscribe((map) => {
            if (!map) return;
            mapSubscription.dispose();
            stackSmallestOnTop(map);
        });
        if (this.map()) {
            mapSubscription.dispose();
            stackSmallestOnTop(this.map());
        }
    }
};

ko.components.unregister('iiif-viewer');
ko.components.register('iiif-viewer', {
    viewModel: IIIFViewerViewmodel,
    template: iiifViewerTemplate,
});

export default IIIFViewerViewmodel;
