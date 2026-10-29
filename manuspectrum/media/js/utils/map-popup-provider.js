/**
 * Shadow of arches/app/media/js/utils/map-popup-provider.js (Arches 8.1.4).
 *
 * Diff vs original:
 *   - the core provider is re-exported with two members replaced; it holds no
 *     copy of the core logic
 *   - `getPopupTemplate` serves the project template `ms-map-popup.htm`
 *     (`map-popup.htm` extended with the summary component on the search map)
 *   - `processData` gives the Mapbox popup the teardown Arches never runs and
 *     warms the summary cache for the resources of the click
 *   - imports `views/components/ms-summary-popup`, which registers the
 *     'ms-summary-popup' component the template mounts
 */

import ko from 'knockout';
import coreProvider from 'arches/arches/app/media/js/utils/map-popup-provider';
import popupTemplate from 'templates/views/components/ms-map-popup.htm';
import { attachMapboxPopupCleanup, warmSummaryCache } from 'utils/summary-popup';
import 'views/components/ms-summary-popup';

const provider = {
    ...coreProvider,

    /**
     * The markup of the popup, as a string.
     *
     * Synchronous because the caller assigns the return value straight into
     * `Popup.setHTML()`. The import is the URL webpack emitted for the
     * template, which Django serves from `/<lang>/templates/…`.
     */
    getPopupTemplate: function () {
        const templateRequest = new XMLHttpRequest();

        templateRequest.open('GET', popupTemplate, false);
        templateRequest.send();
        return templateRequest.responseText;
    },

    /**
     * The popup data, on its way to the binding context.
     *
     * Runs once the popup exists, which is what makes it the place to attach
     * the teardown. The ids are unwrapped because a feature without a resource
     * carries an observable `false` there, and the cache is warmed for the
     * whole click so stepping through several features costs one request.
     */
    processData: function (data) {
        attachMapboxPopupCleanup(data);
        warmSummaryCache(
            ((data && data.popupFeatures) || [])
                .map((feature) => ko.unwrap(feature.resourceinstanceid))
                .filter((id) => typeof id === 'string' && id.length > 0),
        );
        return data;
    },
};

export default provider;
