/**
 * Shadow of arches/app/media/js/views/components/iiif-viewer.js (Arches 8.1.5).
 *
 * Wrapper: the core module is imported through the `arches/arches/app` alias
 * (webpack.common.js) and applied as is; the only core logic reproduced is the
 * annotation loading of `utils/iiif-annotation-nodes`.
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
 *   - `params.buildAnnotationNodes` defaults to `utils/iiif-annotation-nodes`,
 *     which keeps the core's loading of the current canvas and fills the counts
 *     under the thumbnails from one `api/iiif-annotation-counts` request per
 *     annotation node instead of one `iiifannotations` request per canvas (the
 *     core's `preloadAllAnnotations`) and is skipped when the host replaces
 *     `getAnnotationCount`; a function passed by the host wins. The counts are
 *     stricter than the core list: resources the reader cannot read are not
 *     counted, so a thumbnail count can be below the shapes drawn on the canvas.
 *     Differences and core bugs not reproduced: see that module's header
 *   - the core receives a copy of `params`; the host's object is not written to
 *   - the 'iiif-viewer' Knockout component is re-registered on the wrapper
 *   - imports `views/components/ms-summary-popup`, which registers the
 *     'ms-summary-popup' component the binder mounts
 */
import ko from 'knockout';
import CoreIIIFViewerViewmodel from 'arches/arches/app/media/js/views/components/iiif-viewer';
import iiifViewerTemplate from 'templates/views/components/iiif-viewer.htm';
import { createBuildAnnotationNodes } from 'utils/iiif-annotation-nodes';
import { stackSmallestOnTop } from 'utils/leaflet-stack';
import { bindLeafletSummaryPopup } from 'utils/summary-popup';
import 'views/components/ms-summary-popup';

const IIIFViewerViewmodel = function(params) {
    const self = this;
    let coreGetAnnotationCount;
    let viewerParams = params;
    if (params && !params.onEachFeature) {
        viewerParams = { ...viewerParams, onEachFeature: bindLeafletSummaryPopup };
    }
    if (params && !params.buildAnnotationNodes) {
        viewerParams = {
            ...viewerParams,
            buildAnnotationNodes: createBuildAnnotationNodes(
                self,
                () => self.getAnnotationCount === coreGetAnnotationCount,
            ),
        };
    }
    CoreIIIFViewerViewmodel.apply(this, [viewerParams]);
    coreGetAnnotationCount = self.getAnnotationCount;

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
