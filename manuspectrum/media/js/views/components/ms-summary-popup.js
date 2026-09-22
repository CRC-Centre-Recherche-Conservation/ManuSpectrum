/**
 * The summary card shown for one resource on the search map and in the IIIF
 * viewer.
 *
 * Both surfaces mount the same component and differ only in their `params`.
 * The payload it renders is built from curator data, so nothing in it reaches
 * the DOM as markup or as a URL: the template binds with `text:` only, and
 * every `href` is assembled here from `arches.urls.resource_report` and an id
 * the payload must spell as a UUID.
 *
 * The request itself belongs to `utils/summary-popup`, whose refcounted page
 * cache survives the destroy/rebuild cycle both popups put the component
 * through. This viewmodel only holds a reference and gives it back in
 * `dispose()`.
 */

import arches from 'arches';
import ko from 'knockout';
import 'bindings/ms-spark';
import dispose from 'utils/dispose';
import { acquireSummary, invalidateSummary } from 'utils/summary-popup';
import summaryPopupTemplate from 'templates/views/components/ms-summary-popup.htm';

/** The one id shape a report URL is built from. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Refusals of the endpoint, plus the degraded payload, as messages. */
const MESSAGE_KEYS = {
    forbidden: 'summaryForbidden',
    notfound: 'summaryNotFound',
    network: 'summaryError',
    degraded: 'summaryUnavailable',
};

/**
 * The report of one resource, or `null` when the id is not one.
 *
 * `arches.urls.resource_report` already carries the language prefix. An id that
 * is not a UUID comes from a payload the server built from user data, and would
 * be the one way a string from the database could steer a link.
 */
function reportUrlFor(id) {
    return typeof id === 'string' && UUID.test(id)
        ? arches.urls.resource_report + id
        : null;
}

const vm = function (params) {
    const self = this;

    this.resourceId = ko.unwrap(params.resourceId) || null;

    // Both are inputs of the secondary footer action, which v1 does not offer
    // (see `mapUrl`): the surface says which one to propose, the context says
    // which annotation the IIIF popup was opened from.
    this.surface = params.surface || 'map';
    this.context = params.context || null;

    /**
     * The search map popup already draws a title bar and a footer around the
     * component; the card brings its own on the other surfaces.
     */
    this.ownChrome = this.surface !== 'map';
    this.disposables = [];
    this.disposed = false;

    /** The reference on the page cache this instance currently holds. */
    this.handle = null;

    this.loading = ko.observable(false);
    this.errorCode = ko.observable(null);
    this.summary = ko.observable(null);

    const fallbackTitle = ko.unwrap(params.graphName) || '';

    this.title = ko.pureComputed(() => {
        const data = self.summary();
        return (data && data.name) || fallbackTitle;
    });

    this.graphName = ko.pureComputed(() => {
        const data = self.summary();
        return (data && data.graph && data.graph.name) || fallbackTitle;
    });

    this.fields = ko.pureComputed(() => {
        const data = self.summary();
        return (data && data.fields) || [];
    });

    this.rollups = ko.pureComputed(() => {
        const data = self.summary();
        return (data && data.rollups) || [];
    });

    this.preview = ko.pureComputed(() => {
        const data = self.summary();
        return (data && data.preview) || null;
    });

    /** A model with no `summary` configuration keeps the Arches rendering. */
    this.legacy = ko.pureComputed(() => {
        const data = self.summary();
        return Boolean(data) && data.configured === false;
    });

    this.mapPopup = ko.pureComputed(() => {
        const data = self.summary();
        return (self.legacy() && data.map_popup) || '';
    });

    this.hasGeometry = ko.pureComputed(() => {
        const data = self.summary();
        return Boolean(data && data.has_geometry);
    });

    /**
     * No deep link into the search map exists in v1.
     *
     * The footer block stays under `if: mapUrl` so a v2 that can address a
     * feature only has to fill this in, using `surface` and `hasGeometry`.
     */
    this.mapUrl = ko.pureComputed(() => null);

    this.reportUrl = ko.pureComputed(() => reportUrlFor(self.resourceId));

    this.reportUrlFor = reportUrlFor;

    /**
     * What the binding of Task 11 needs to draw the spectrum, or `null`.
     *
     * The series itself is fetched by the binding: the summary payload carries
     * only which file to draw.
     */
    this.spark = ko.pureComputed(() => {
        const preview = self.preview();
        return preview && preview.file_id
            ? { fileId: preview.file_id, title: preview.label || '' }
            : null;
    });

    this.previewLabel = ko.pureComputed(() => {
        const spectrum = arches.translations.summarySpectrum;
        const preview = self.preview();
        return preview && preview.label ? `${spectrum} — ${preview.label}` : spectrum;
    });

    this.errorMessage = ko.pureComputed(() => {
        const key = MESSAGE_KEYS[self.errorCode()];
        return key ? arches.translations[key] : '';
    });

    /** A configured resource whose every field and rollup came back empty. */
    this.isEmpty = ko.pureComputed(
        () =>
            Boolean(self.summary()) &&
            !self.legacy() &&
            !self.errorCode() &&
            !self.fields().length &&
            !self.rollups().length &&
            !self.spark()
    );

    this.emptyMessage = ko.pureComputed(() => arches.translations.summaryEmpty);

    /** `+{n}`, the overflow marker of a truncated value or item list. */
    this.moreLabel = (count) =>
        String(arches.translations.summaryMore || '+{n}').replace('{n}', count);

    /** Plain values of a `text`, `date` or `number` field, as one string. */
    this.joinValues = (values) => (Array.isArray(values) ? values.join(' – ') : '');

    /**
     * Take a reference on the summary and render whatever it resolves to.
     *
     * The answer of a reference `retry()` has replaced is dropped: the cache
     * keeps a settled promise, so the previous one can still land.
     */
    const load = () => {
        self.errorCode(null);
        self.summary(null);
        if (!self.resourceId) {
            self.loading(false);
            self.errorCode('notfound');
            return;
        }
        self.loading(true);
        const handle = acquireSummary(self.resourceId);
        self.handle = handle;
        handle.promise.then((result) => {
            if (self.disposed || self.handle !== handle) return;
            self.loading(false);
            if (!result || result.status !== 'ok') {
                self.errorCode((result && result.status) || 'network');
                return;
            }
            const data = result.data || {};
            self.summary(data);
            if (data.degraded) self.errorCode('degraded');
        });
    };

    this.retry = () => {
        if (self.handle) self.handle.release();
        self.handle = null;
        // Dropping the settled entry is what makes the next acquisition reach
        // the server: `acquireSummary` keeps a promise that settled on a
        // refusal just as it keeps one that settled on a payload.
        invalidateSummary(self.resourceId);
        load();
    };

    this.dispose = () => {
        self.disposed = true;
        if (self.handle) self.handle.release();
        self.handle = null;
        dispose(self);
    };

    load();
};

export default ko.components.register('ms-summary-popup', {
    viewModel: vm,
    template: summaryPopupTemplate,
});
