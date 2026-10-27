/**
 * Shadow of arches/app/media/js/models/report.js (Arches 8.1.5).
 *
 * Wrapper, no core code copied: the core model is imported through the
 * `arches/arches/app` alias (webpack.common.js) and extended.
 *
 * Diff vs original:
 *   - the related resources summary of the report API (an array of
 *     `{graphid, name, resources}`) is keyed by graph id instead of by its
 *     position, so « Load more » and « Load all » ask for the right graph
 *   - that summary holds at most RELATED_RESOURCES_EXPORT_LIMIT relations and
 *     no paginator. When the resource may have more (the count of page 1 of
 *     the paginated route is above the cap less one page), every graph's list
 *     is reloaded from page 1 of `related_resources/<id>?resourceinstance_graphid=<g>`
 *     (RELATED_RESOURCES_PER_PAGE a page): its « Load more » reaches every
 *     relation
 *   - « Load all » on a graph with more relations than the cap loads the next
 *     pages up to about the cap (whole pages) and keeps the paginator, instead
 *     of one capped list that would end the paging; a click during that chain
 *     waits for it
 * The cap and the page size come from `arches` (`arches-data` in the project's
 * templates/javascript.htm).
 */
import $ from 'jquery';
import ko from 'knockout';
import arches from 'arches';
import CoreReportModel from 'arches/arches/app/media/js/models/report';

function relationsLimit() {
    return Number(arches.relatedResourcesExportLimit);
}

function relationsPerPage() {
    return Number(arches.relatedResourcesPerPage);
}

/** The « Load all » page chain running for a graph's entry, if any. */
const loadingPages = new WeakMap();

export default CoreReportModel.extend({
    initialize: function(options) {
        CoreReportModel.prototype.initialize.call(this, options);
        if (
            Array.isArray(options.related_resources) &&
            this.attributes.resourceid &&
            relationsLimit() > 0 &&
            relationsPerPage() > 0
        ) {
            this.relatedResourcesPaged = this.pageCutRelatedResources();
        }
    },

    updateRelatedResourcesLookup: function(json) {
        const keyed = Array.isArray(json)
            ? Object.fromEntries(json.map((entry) => [entry.graphid, entry]))
            : json;
        return CoreReportModel.prototype.updateRelatedResourcesLookup.call(this, keyed);
    },

    /**
     * While a « Load all » page chain runs for a graph, any other click on
     * that graph's buttons gets the same chain instead of a second request.
     */
    getRelatedResources: function(loadAll, resource) {
        const running = loadingPages.get(resource);
        if (running) {
            return running;
        }
        if (loadAll && resource.totalRelatedResources > relationsLimit()) {
            const chain = this.loadNextPages(resource, Math.ceil(relationsLimit() / relationsPerPage()))
                .catch(function(error) {
                    console.warn('Related resources: stopped loading pages', error);
                })
                .finally(function() {
                    loadingPages.delete(resource);
                });
            loadingPages.set(resource, chain);
            return chain;
        }
        return CoreReportModel.prototype.getRelatedResources.call(this, loadAll, resource);
    },

    /** Loads up to `pages` next pages of one graph's list, one after the other; the first failure ends it. */
    loadNextPages: function(resource, pages) {
        const self = this;
        const next = function(left) {
            const paginator = resource.paginator();
            if (left <= 0 || !paginator || !paginator.has_next) {
                return Promise.resolve();
            }
            return Promise.resolve(
                CoreReportModel.prototype.getRelatedResources.call(self, false, resource),
            ).then(() => next(left - 1));
        };
        return next(pages);
    },

    /**
     * Pages every graph's related resources when the summary may have been
     * cut. The count comes from page 1 of the route (one count, fifteen rows);
     * it counts the relations before the read check of the rows beyond page
     * 1, so the test is `count > cap - page`. Once every graph's page 1 has
     * arrived, a new lookup is built from them in the same graph order and
     * swapped in: new entries, which the report template renders again. A
     * failed request keeps the summary.
     */
    pageCutRelatedResources: function() {
        const self = this;
        const url = arches.urls.related_resources + this.attributes.resourceid;
        const fetchPage = (data) => Promise.resolve($.ajax({ url: url, data: data, dataType: 'json' }));
        return fetchPage({ page: 1 })
            .then(function(json) {
                if (json.related_resources.total.value <= relationsLimit() - relationsPerPage()) {
                    return;
                }
                const graphIds = Object.keys(self.relatedResourcesLookup());
                return Promise.all(
                    graphIds.map((graphId) => fetchPage({ page: 1, resourceinstance_graphid: graphId })),
                ).then(function(pages) {
                    const paged = {};
                    graphIds.forEach(function(graphId, index) {
                        paged[graphId] = pages[index];
                    });
                    const shown = self.relatedResourcesLookup;
                    const built = ko.observable({});
                    self.relatedResourcesLookup = built;
                    try {
                        self.updateRelatedResourcesLookup(paged);
                    } finally {
                        self.relatedResourcesLookup = shown;
                    }
                    shown(built());
                });
            })
            .catch(function(error) {
                console.warn('Related resources: kept the report summary', error);
            });
    },
});
