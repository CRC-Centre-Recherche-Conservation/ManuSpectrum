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
 *     clicks; the shapes of the host's own `drawLayer` (the annotation
 *     widget's editable tile) stay above them all, as the core draws them
 *   - the core receives a copy of `params`; the host's object is not written to
 *   - the 'iiif-viewer' Knockout component is re-registered on the wrapper
 *   - imports `views/components/ms-summary-popup`, which registers the
 *     'ms-summary-popup' component the binder mounts
 */
import ko from 'knockout';
import CoreIIIFViewerViewmodel from 'arches/arches/app/media/js/views/components/iiif-viewer';
import iiifViewerTemplate from 'templates/views/components/iiif-viewer.htm';
import { stackSmallestOnTop } from 'utils/leaflet-stack';
import { bindLeafletSummaryPopup } from 'utils/summary-popup';
import 'views/components/ms-summary-popup';

const IIIFViewerViewmodel = function(params) {
    const viewerParams =
        params && !params.onEachFeature
            ? { ...params, onEachFeature: bindLeafletSummaryPopup }
            : params;
    CoreIIIFViewerViewmodel.apply(this, [viewerParams]);

    const self = this;
    const drawnByHost = (layer) => {
        const drawn = ko.isObservable(self.drawLayer) ? self.drawLayer() : null;
        return Boolean(drawn && typeof drawn.hasLayer === 'function' && drawn.hasLayer(layer));
    };
    const restack = (map) => stackSmallestOnTop(map, undefined, drawnByHost);

    if (ko.isObservable(this.map)) {
        const mapSubscription = this.map.subscribe((map) => {
            if (!map) return;
            mapSubscription.dispose();
            restack(map);
        });
        if (this.map()) {
            mapSubscription.dispose();
            restack(this.map());
        }
    }
};

ko.components.unregister('iiif-viewer');
ko.components.register('iiif-viewer', {
    viewModel: IIIFViewerViewmodel,
    template: iiifViewerTemplate,
});

export default IIIFViewerViewmodel;
