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
 *   - the 'iiif-viewer' Knockout component is re-registered on the wrapper
 */
import ko from 'knockout';
import CoreIIIFViewerViewmodel from 'arches/arches/app/media/js/views/components/iiif-viewer';
import iiifViewerTemplate from 'templates/views/components/iiif-viewer.htm';
import { bindLeafletSummaryPopup } from 'utils/summary-popup';

const IIIFViewerViewmodel = function(params) {
    if (params && !params.onEachFeature) {
        params.onEachFeature = bindLeafletSummaryPopup;
    }
    CoreIIIFViewerViewmodel.apply(this, [params]);
};

ko.components.unregister('iiif-viewer');
ko.components.register('iiif-viewer', {
    viewModel: IIIFViewerViewmodel,
    template: iiifViewerTemplate,
});

export default IIIFViewerViewmodel;
