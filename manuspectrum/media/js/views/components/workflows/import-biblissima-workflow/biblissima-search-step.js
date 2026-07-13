/**
 * Import Biblissima workflow — step 2 (Search & Curate).
 *
 * Queries Biblissima via the backend proxy and builds an in-memory cart
 * of items to create at step 3. Three search modes, all gated on the
 * resourceType picked at step 1:
 *
 *   - **Document mode** (`searchManuscripts`): searches manuscripts by
 *     name/shelfmark via the Wikibase suggest endpoint.
 *   - **Component mode, descriptor sub-mode** (`searchComponents`): resolves
 *     selected iconographic descriptors to portal hashes and hits the IIIF
 *     manifest search. Progressive loading: blocks on page 1, streams the
 *     rest in the background behind an AbortController so switching modes
 *     cancels cleanly.
 *   - **Component mode, manuscript sub-mode** (`searchManuscriptIlluminations`):
 *     resolves a manuscript QID/ARK to its portal hash, then scrapes its
 *     illumination list page-by-page.
 *
 * Cart cap is hard (10 Documents / 25 Components) — enforced in every
 * add path (`toggleCartItem`, `addByIdentifier`, `addAllVisible`). The
 * cap is editorial, not technical: imports cost analyst time downstream.
 *
 * Output: ``params.value({ selectedItems: ko.toJS(cart), descriptors })``
 * — the full cart snapshot for step 3 to consume via ``searchStepData``.
 *
 * No DB writes anywhere in this step. All fetches are read-only proxy
 * calls (`/api/biblissima/search*`, `/entity/`, `/suggest`, …).
 */
import ko from 'knockout';
import arches from 'arches';
import 'bindings/select2-query';
import 'bindings/thumb-fallback';
import noUiSlider from 'nouislider';
import biblissimaSearchStepTemplate from 'templates/views/components/workflows/import-biblissima-workflow/biblissima-search-step.htm';

const DATE_MIN = -2000;
const DATE_MAX = 1850;

// Simple binding to call an init function when the element is rendered
ko.bindingHandlers.sliderInit = {
    init: function(element, valueAccessor) {
        const initFn = valueAccessor();
        if (typeof initFn === 'function') {
            // Small delay to ensure element is in DOM with dimensions
            setTimeout(() => initFn(element), 50);
        }
    }
};

const viewModel = function(params) {
    const self = this;

    // Workflow step interface
    this.complete = params.form?.complete || ko.observable(false);
    this.saving = ko.observable(false);
    this.searching = ko.observable(false);
    this.searchError = ko.observable(null);

    // Progressive loading state for the component search:
    // page 1 is awaited blocking, pages 2..N stream in background.
    this.loadingProgress = ko.observable({
        loaded: 0,
        total: 0,
        loadedPages: 0,
        totalPages: 0,
    });
    this.isProgressiveLoading = ko.computed(() => {
        const p = self.loadingProgress();
        return p.totalPages > 0 && p.loadedPages < p.totalPages;
    });
    this.loadingProgressPercent = ko.computed(() => {
        const p = self.loadingProgress();
        if (!p.total) return 0;
        return Math.round((p.loaded / p.total) * 100);
    });
    // AbortController for in-flight background page fetches. Replaced on every
    // new search so previous background loads get cancelled cleanly.
    this._pageLoadAbort = null;

    // Loading state: rotating message + elapsed timer while waiting for
    // first results. Works uniformly across all search modes.
    this.loadingElapsed = ko.observable(0); // seconds
    this._loadingTimer = null;
    this.loadingElapsedDisplay = ko.computed(() => {
        const s = self.loadingElapsed();
        const mm = Math.floor(s / 60).toString().padStart(2, '0');
        const ss = (s % 60).toString().padStart(2, '0');
        return `${mm}:${ss}`;
    });
    this.loadingMessage = ko.computed(() => {
        const s = self.loadingElapsed();
        const t = arches.translations;
        if (s < 5) return t.biblissimaLoadingConnecting || 'Connecting to Biblissima…';
        if (s < 15) return t.biblissimaLoadingFetching || 'Fetching manuscripts from the archive…';
        if (s < 35) return t.biblissimaLoadingEnriching || 'Enriching manuscript metadata…';
        if (s < 60) return t.biblissimaLoadingMatching || 'Matching records…';
        return t.biblissimaLoadingStillWorking || 'Still working — large searches may take up to 2 minutes';
    });
    this.loadingShowReassurance = ko.computed(() => self.loadingElapsed() >= 20);

    this._startLoadingTimers = () => {
        self.loadingElapsed(0);
        if (self._loadingTimer) clearInterval(self._loadingTimer);
        const started = Date.now();
        self._loadingTimer = setInterval(() => {
            self.loadingElapsed(Math.floor((Date.now() - started) / 1000));
        }, 1000);
    };

    this._stopLoadingTimers = () => {
        if (self._loadingTimer) {
            clearInterval(self._loadingTimer);
            self._loadingTimer = null;
        }
        self.loadingElapsed(0);
    };

    // Wire loading timer to the searching observable so all 3 search modes
    // (Document, Component by descriptor, Component by manuscript) get the
    // same loading state without each having to call _startLoadingTimers().
    this.searching.subscribe((isSearching) => {
        if (isSearching) {
            self._startLoadingTimers();
        } else {
            self._stopLoadingTimers();
        }
    });

    // Reset search state when switching between Component sub-modes
    // (descriptor / manuscript). Otherwise the meta bar keeps showing the
    // previous mode's selectedManuscriptLabel and totalResults, and the
    // results grid stays populated with stale cards.
    this._resetSearchState = () => {
        if (self._pageLoadAbort) {
            self._pageLoadAbort.abort();
            self._pageLoadAbort = null;
        }
        self.searching(false);
        self.hasSearched(false);
        self.searchError(null);
        self.searchResults([]);
        self.currentPage(1);
        if (self.textFilter) self.textFilter('');
        self.selectedManuscriptLabel('');
        self.selectedManuscriptHash('');
        self.loadingProgress({
            loaded: 0,
            total: 0,
            loadedPages: 0,
            totalPages: 0,
        });
    };

    // Config from step 1
    this.config = params.configStepData || {};
    this.resourceType = this.config.resourceType || 'Document';
    this.isDocument = this.resourceType === 'Document';
    this.isComponent = this.resourceType === 'Component';

    // Component search mode: 'descriptor' (IIIF search) or 'manuscript' (portal scraping)
    this.componentSearchMode = ko.observable('descriptor');
    // Reset search state when switching between Component sub-modes so the
    // meta bar and stale results from the previous mode don't leak over.
    this.componentSearchMode.subscribe(() => {
        self._resetSearchState();
    });

    // Search state — all results stored, paginated client-side
    this.searchResults = ko.observableArray();
    this.currentPage = ko.observable(1);
    this.hasSearched = ko.observable(false);

    // Cart — hard cap forces the user to curate selections rather than
    // bulk-importing search results. Resources are only created when an
    // analysis campaign justifies it, so we keep the Document limit tight.
    this.cart = ko.observableArray();
    this.cartCount = ko.computed(() => self.cart().length);
    this.cartMax = self.isDocument ? 10 : 25;
    this.cartIsFull = ko.computed(() => self.cart().length >= self.cartMax);
    this.cartLimitLabel = arches.translations.biblissimaCartLimitReached || 'Cart limit reached';
    this.cartAddAllTooManyLabel =
        arches.translations.biblissimaCartAddAllTooMany ||
        'Too many results on this page for the remaining cart slots — reduce the page size or unselect some';

    // =====================
    // SHARED: filters panel (collapsible)
    // =====================
    this.showFilters = ko.observable(false);
    this.toggleFilters = () => self.showFilters(!self.showFilters());
    this.pageSize = ko.observable('20');
    // Effective limit: 0 means "all" → show everything on one page
    this.effectiveLimit = ko.computed(() => {
        const val = parseInt(self.pageSize(), 10);
        return val === 0 ? Number.MAX_SAFE_INTEGER : val;
    });

    // Date range slider
    this.dateFrom = ko.observable(DATE_MIN);
    this.dateTo = ko.observable(DATE_MAX);
    this.dateRangeActive = ko.computed(() =>
        self.dateFrom() > DATE_MIN || self.dateTo() < DATE_MAX
    );
    this.dateRangeLabel = ko.computed(() => {
        if (!self.dateRangeActive()) return '';
        const from = self.dateFrom();
        const to = self.dateTo();
        const fromLabel = from < 0 ? `${Math.abs(from)} av. J.-C.` : `${from} ap. J.-C.`;
        const toLabel = to < 0 ? `${Math.abs(to)} av. J.-C.` : `${to} ap. J.-C.`;
        return `${fromLabel} — ${toLabel}`;
    });

    // Client-side date filtering + pagination
    this._parseDateRange = (dateStr) => {
        if (!dateStr) return null;
        const s = String(dateStr);
        // "13e siècle" → 1201–1300
        const centuryMatch = s.match(/(\d+)e\s+si[eè]cle/i);
        if (centuryMatch) {
            const c = parseInt(centuryMatch[1], 10);
            return [(c - 1) * 100 + 1, c * 100];
        }
        // "1201-1300" or "1201 - 1300"
        const rangeMatch = s.match(/(-?\d+)\s*[-–—]\s*(-?\d+)/);
        if (rangeMatch) return [parseInt(rangeMatch[1], 10), parseInt(rangeMatch[2], 10)];
        // Single year "1250"
        const yearMatch = s.match(/(-?\d{3,4})/);
        if (yearMatch) { const y = parseInt(yearMatch[1], 10); return [y, y]; }
        return null;
    };

    // Free-text filter on top of the date filter. Tokenize the query on
    // whitespace, normalize (lowercase + accent strip), and require every
    // token to appear as a substring in the haystack built from the
    // user-visible fields. Fast — O(items × fields × tokens) — and good
    // enough for "find where in 500 results my Latin 9926 hides" without
    // pulling in a fuzzy-search dependency.
    this.textFilter = ko.observable('');
    this.textFilterActive = ko.computed(() => self.textFilter().trim().length > 0);
    this.clearTextFilter = () => self.textFilter('');

    const _normalize = (s) =>
        String(s || '')
            .toLowerCase()
            .normalize('NFD')
            // Strip Unicode combining diacritics (U+0300..U+036F) so that
            // "Latin" matches "Lâtin", "Latín", "Lätïn", etc.
            .replace(/[̀-ͯ]/g, '');

    const _haystack = (item) => {
        // Concatenate every searchable field. Descriptors is an array,
        // join with spaces. Includes manuscript ARK/QID so users can
        // also search by identifier fragments.
        const parts = [
            item.label, item.legend, item.shelfmark, item.collectionLabel,
            item.manuscript, item.folio, item.date, item.location,
            item.authorLabel, item.locationLabel, item.parentInstitutionLabel,
            item.arkId, item.biblissimaQid, item.mandragoreId,
            (item.descriptors || []).join(' '),
        ];
        return _normalize(parts.filter(Boolean).join(' '));
    };

    // Compile a token to a matcher function. Numeric tokens (purely
    // digits) must be **standalone words** in the haystack — surrounded
    // by non-word characters on both sides — so that typing "4" doesn't
    // also match digits embedded in hex hashes (``e4e`` in an ARK), in
    // longer numbers (``452``, ``342``), or inside date phrases like
    // ``14e siècle``. ``\b`` enforces the word boundary against any
    // word char (letter or digit), which is exactly the behavior we
    // want here. Non-numeric tokens keep cheap substring matching for
    // friendly free-text search ("abdi" → "Abdias").
    const _ALL_DIGITS_RE = /^\d+$/;
    const _compileToken = (token) => {
        if (_ALL_DIGITS_RE.test(token)) {
            const re = new RegExp('\\b' + token + '\\b');
            return (hay) => re.test(hay);
        }
        const needle = token;
        return (hay) => hay.indexOf(needle) !== -1;
    };

    this._matchesTextFilter = (item, matchers) => {
        if (!matchers || matchers.length === 0) return true;
        const hay = _haystack(item);
        for (let i = 0; i < matchers.length; i++) {
            if (!matchers[i](hay)) return false;
        }
        return true;
    };

    this.filteredResults = ko.computed(() => {
        const all = self.searchResults();
        const dateActive = self.dateRangeActive();
        const textActive = self.textFilterActive();
        if (!dateActive && !textActive) return all;

        const from = self.dateFrom();
        const to = self.dateTo();
        // Pre-compile token matchers once per filter pass — avoids
        // re-building a RegExp for every item in the result set.
        const matchers = textActive
            ? _normalize(self.textFilter())
                .split(/\s+/)
                .filter(Boolean)
                .map(_compileToken)
            : [];

        return all.filter((item) => {
            if (dateActive) {
                const range = self._parseDateRange(item.date);
                // Items without parseable date are kept (don't penalize
                // entries the connector couldn't date).
                if (range && !(range[1] >= from && range[0] <= to)) return false;
            }
            if (textActive && !self._matchesTextFilter(item, matchers)) return false;
            return true;
        });
    });

    this.totalResults = ko.computed(() => self.filteredResults().length);
    // Total before any client-side filter, used to render "X / Y results"
    // when a filter narrows the pool.
    this.totalUnfilteredResults = ko.computed(() => self.searchResults().length);
    this.totalPages = ko.computed(() => {
        const limit = self.effectiveLimit();
        return Math.ceil(self.filteredResults().length / limit) || 0;
    });
    this.pagedResults = ko.computed(() => {
        const all = self.filteredResults();
        const limit = self.effectiveLimit();
        const page = self.currentPage();
        const start = (page - 1) * limit;
        return all.slice(start, start + limit);
    });
    // Reset to page 1 when page size or any filter changes — without this
    // the user can land on an out-of-range page after narrowing the set.
    this.effectiveLimit.subscribe(() => self.currentPage(1));
    this.dateFrom.subscribe(() => self.currentPage(1));
    this.dateTo.subscribe(() => self.currentPage(1));
    this.textFilter.subscribe(() => self.currentPage(1));

    // Direct identifier input. Two accepted shapes:
    //   - QID (manuscript): bare Q-prefixed id, or pasted entity/Item URL.
    //   - ifdata ARK (single illumination, Component mode only): direct
    //     add via the dedicated portal scrape endpoint. Illuminations
    //     have no Wikibase entity, so QID is not a substitute here.
    // mdata ARKs (manuscript hashes) are intentionally rejected: there's
    // no hash→QID resolver wired in, and the prior fallback through
    // /suggest only matched labels and silently bailed.
    this.directIdentifier = ko.observable('');
    this.addingDirect = ko.observable(false);

    const _QID_RE = /Q\d+/i;
    const _IFDATA_RE = /ifdata\w+/i;
    const _normalizeQid = (input) => {
        if (!input) return null;
        const m = String(input).trim().match(_QID_RE);
        return m ? m[0].toUpperCase() : null;
    };

    this._addIlluminationByArk = async (raw) => {
        const m = String(raw).match(_IFDATA_RE);
        if (!m) return;
        const hash = m[0];

        self.searchError(null);
        self.addingDirect(true);
        try {
            const resp = await fetch(`/api/biblissima/illumination/${hash}`);
            if (!resp.ok) {
                self.searchError(
                    arches.translations.biblissimaIdentifierNotFound ||
                        'No Biblissima entity matches this identifier'
                );
                return;
            }
            const detail = await resp.json();
            const item = {
                canvasId: detail.ifdataHash,
                arkId: detail.arkId,
                label: detail.label || '',
                thumbnail: detail.thumbnail || null,
                manuscript: detail.manuscript || '',
                folio: detail.folio || '',
                legend: detail.label || '',
                date: detail.date || '',
                location: detail.location || '',
                descriptors: detail.descriptors || [],
                portalUrl: detail.portalUrl || '',
                manifestUrl: detail.manifestUrl || '',
                imageUrl: detail.imageUrl || '',
                // Manuscript-level fields populated server-side by
                // _enrich_canvases. Needed by the step 3 parent-resolver
                // (biblissimaQid + manuscriptArk) and by the dependency
                // panel (location / institution / author).
                manuscriptArk: detail.manuscriptArk || '',
                biblissimaQid: detail.biblissimaQid || '',
                shelfmark: detail.shelfmark || '',
                collectionLabel: detail.collectionLabel || '',
                collectionQid: detail.collectionQid || '',
                locationLabel: detail.locationLabel || '',
                locationQid: detail.locationQid || '',
                geonamesId: detail.geonamesId || '',
                parentInstitutionLabel: detail.parentInstitutionLabel || '',
                parentInstitutionQid: detail.parentInstitutionQid || '',
                authorLabel: detail.authorLabel || '',
                authorQid: detail.authorQid || '',
                mandragoreId: detail.mandragoreId || '',
                digitizationUrl: detail.digitizationUrl || '',
                hasImage: !!detail.imageUrl,
                typeValueId: detail.typeValueId || '',
                typeLabel: detail.typeLabel || '',
                ifdataHash: detail.ifdataHash,
                mandragoreArk: detail.mandragoreArk || '',
            };
            const exists = self.cart().some((c) => self._sameItem(c, item));
            if (!exists && !self.cartIsFull()) self.cart.push(item);
            self.directIdentifier('');
        } catch (err) {
            console.error('Failed to add illumination by ARK:', err);
            self.searchError(
                arches.translations.biblissimaNetworkError ||
                    'Network error while querying Biblissima'
            );
        } finally {
            self.addingDirect(false);
        }
    };

    this.addByIdentifier = async () => {
        const raw = self.directIdentifier().trim();
        if (!raw) return;

        if (self.isComponent && _IFDATA_RE.test(raw)) {
            await self._addIlluminationByArk(raw);
            return;
        }

        const qid = _normalizeQid(raw);
        if (!qid) {
            self.searchError(
                arches.translations.biblissimaIdentifierInvalid ||
                    'Paste a Biblissima QID (e.g. Q63633)'
            );
            return;
        }

        self.searchError(null);
        self.addingDirect(true);
        try {
            const resp = await fetch(`/api/biblissima/entity/${qid}`);
            if (!resp.ok) {
                self.searchError(
                    arches.translations.biblissimaIdentifierNotFound ||
                        'No Biblissima entity matches this identifier'
                );
                return;
            }
            const d = await resp.json();

            // Component mode delegates to the manuscript-illuminations flow
            // so we get the same paginated streaming + entity enrichment as
            // the autocomplete path.
            if (self.isComponent && d.portalHash) {
                self.manuscriptForComponent(qid);
                await self.searchManuscriptIlluminations();
                self.directIdentifier('');
                return;
            }

            const item = self._entityToItem(d);
            const exists = self.cart().some((c) => self._sameItem(c, item));
            if (!exists && !self.cartIsFull()) self.cart.push(item);
            self.directIdentifier('');
        } catch (err) {
            console.error('Failed to add by identifier:', err);
            self.searchError(
                arches.translations.biblissimaNetworkError ||
                    'Network error while querying Biblissima'
            );
        } finally {
            self.addingDirect(false);
        }
    };

    // =====================
    // DOCUMENT MODE: search by manuscript name/shelfmark
    // =====================
    this.manuscriptQuery = ko.observable('');

    this._entityToItem = (d) => ({
        canvasId: d.biblissimaQid,
        arkId: d.portalHash ? `ark:/43093/${d.portalHash}` : null,
        label: d.label || '',
        thumbnail: null,
        manuscript: d.shelfmark || d.label || '',
        folio: '',
        legend: d.label || '',
        date: d.date || '',
        location: d.locationLabel || '',
        descriptors: [],
        portalUrl: d.portalHash ? `https://portail.biblissima.fr/ark:/43093/${d.portalHash}` : '',
        manifestUrl: d.manifestUrl || '',
        authorLabel: d.authorLabel || '',
        authorQid: d.authorQid || '',
        biblissimaQid: d.biblissimaQid || '',
        shelfmark: d.shelfmark || '',
        mandragoreId: d.mandragoreId || '',
        collectionLabel: d.collectionLabel || '',
        digitizationUrl: d.digitizationUrl || '',
        // Location & owner from collection resolution
        locationLabel: d.locationLabel || '',
        locationQid: d.locationQid || '',
        geonamesId: d.geonamesId || '',
        parentInstitutionLabel: d.parentInstitutionLabel || '',
        parentInstitutionQid: d.parentInstitutionQid || '',
    });

    // =====================
    // COMPONENT MODE "By manuscript": search a manuscript, then get its illuminations
    // =====================
    this.manuscriptForComponent = ko.observable('');
    this.selectedManuscriptLabel = ko.observable('');
    this.selectedManuscriptHash = ko.observable('');

    // Select2 config for manuscript autocomplete in Component mode
    this.manuscriptForComponentSelect = ko.observable(null);
    this.manuscriptComponentSelectConfig = {
        value: self.manuscriptForComponentSelect,
        clickBubble: true,
        multiple: false,
        closeOnSelect: true,
        allowClear: true,
        placeholder: arches.translations.biblissimaSearchManuscriptForComponent || 'Search a manuscript to see its illuminations...',
        minimumInputLength: 3,
        ajax: {
            url: '/api/biblissima/suggest',
            dataType: 'json',
            quietMillis: 300,
            data: (requestParams) => ({ q: requestParams.term || '', type: 'manuscript', limit: 15 }),
            processResults: (data) => ({
                results: (data.results || []).map((item) => ({
                    id: item.id,
                    text: item.label,
                })),
            }),
        },
        templateResult: (item) => item.text || '',
        templateSelection: (item) => item.text || '',
        escapeMarkup: (m) => m,
    };

    // When a manuscript is selected from autocomplete, load its illuminations
    this.manuscriptForComponentSelect.subscribe(async (qid) => {
        if (!qid) return;
        self.manuscriptForComponent(qid);
        await self.searchManuscriptIlluminations();
        // Don't clear — keep the selection visible
    });

    // Map a raw illumination from the portal scrape to a result card shape,
    // merging in manuscript-level data from the resolved Wikibase entity.
    this._illuminationToResult = (item, entityData, manuscriptLabel) => ({
        canvasId: item.ifdataHash,
        arkId: item.arkId,
        label: item.label,
        thumbnail: null,
        manuscript: manuscriptLabel,
        folio: item.folio,
        legend: item.descriptor,
        date: '',
        location: '',
        descriptors: [item.descriptor],
        portalUrl: item.portalUrl,
        manifestUrl: entityData.manifestUrl || '',
        authorLabel: entityData.authorLabel || '',
        authorQid: entityData.authorQid || '',
        biblissimaQid: entityData.biblissimaQid || '',
        shelfmark: entityData.shelfmark || '',
        mandragoreId: entityData.mandragoreId || '',
        collectionLabel: entityData.collectionLabel || '',
        digitizationUrl: entityData.digitizationUrl || '',
        locationLabel: entityData.locationLabel || '',
        locationQid: entityData.locationQid || '',
        geonamesId: entityData.geonamesId || '',
        parentInstitutionLabel: entityData.parentInstitutionLabel || '',
        parentInstitutionQid: entityData.parentInstitutionQid || '',
        hasImage: item.hasImage,
        typeValueId: item.typeValueId || '',
        typeLabel: item.typeLabel || '',
        ifdataHash: item.ifdataHash,
    });

    this.searchManuscriptIlluminations = async () => {
        const query = self.manuscriptForComponent().trim();
        if (!query) return;

        // Cancel any in-flight background page fetches from a previous search
        if (self._pageLoadAbort) {
            self._pageLoadAbort.abort();
        }
        const abortController = new AbortController();
        self._pageLoadAbort = abortController;

        self.searching(true);
        self.searchError(null);
        self.hasSearched(true);
        self.currentPage(1);
        self.searchResults([]);
        self.loadingProgress({
            loaded: 0,
            total: 0,
            loadedPages: 0,
            totalPages: 0,
        });

        const PAGE_SIZE = 20;

        try {
            let entityData;

            // If query looks like a QID (Q + digits), fetch entity directly
            if (/^Q\d+$/i.test(query)) {
                const entityResp = await fetch(
                    `/api/biblissima/entity/${query}`,
                    { signal: abortController.signal },
                );
                if (!entityResp.ok) { self.searching(false); return; }
                entityData = await entityResp.json();
            } else {
                // Search by text
                const suggestResp = await fetch(
                    `/api/biblissima/suggest?q=${encodeURIComponent(query)}&limit=10&type=manuscript`,
                    { signal: abortController.signal },
                );
                const suggestData = await suggestResp.json();
                if (!suggestData.results?.length) {
                    self.searchResults([]);
                    self.searching(false);
                    return;
                }
                const entityResp = await fetch(
                    `/api/biblissima/entity/${suggestData.results[0].id}`,
                    { signal: abortController.signal },
                );
                entityData = await entityResp.json();
            }

            const portalHash = entityData.portalHash;
            if (!portalHash) {
                self.searchResults([]);
                self.searching(false);
                return;
            }

            const manuscriptLabel = entityData.label || query;
            self.selectedManuscriptLabel(manuscriptLabel);
            self.selectedManuscriptHash(portalHash);

            // --- Stage 1: blocking fetch of page 1 ---
            const firstUrl = `/api/biblissima/manuscript-illuminations?portalHash=${portalHash}&page=1&page_size=${PAGE_SIZE}`;
            const firstResp = await fetch(firstUrl, {
                signal: abortController.signal,
            });
            const firstData = await firstResp.json().catch(() => ({}));
            if (!firstResp.ok) {
                self.searchError(
                    firstData.message ||
                        arches.translations.biblissimaSearchFailed ||
                        'Biblissima search failed',
                );
                self.searchResults([]);
                self.searching(false);
                return;
            }

            const firstResults = (firstData.results || []).map((item) =>
                self._illuminationToResult(item, entityData, manuscriptLabel),
            );
            self.searchResults(firstResults);
            self.searching(false); // page 1 visible

            const total = firstData.total || firstResults.length;
            const totalPages = firstData.total_pages || 1;
            self.loadingProgress({
                loaded: firstResults.length,
                total: total,
                loadedPages: 1,
                totalPages: totalPages,
            });

            // --- Stage 2: background, sequential load of pages 2..N ---
            for (let page = 2; page <= totalPages; page++) {
                if (abortController.signal.aborted) return;
                try {
                    const pageUrl = `/api/biblissima/manuscript-illuminations?portalHash=${portalHash}&page=${page}&page_size=${PAGE_SIZE}`;
                    const pageResp = await fetch(pageUrl, {
                        signal: abortController.signal,
                    });
                    if (!pageResp.ok) continue;
                    const pageData = await pageResp.json();
                    const pageResults = (pageData.results || []).map((item) =>
                        self._illuminationToResult(item, entityData, manuscriptLabel),
                    );

                    const current = self.searchResults();
                    self.searchResults(current.concat(pageResults));
                    self.loadingProgress({
                        loaded: self.searchResults().length,
                        total: total,
                        loadedPages: page,
                        totalPages: totalPages,
                    });
                } catch (err) {
                    if (err.name === 'AbortError') return;
                    console.warn(`Biblissima illuminations page ${page} load failed`, err);
                }
            }
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('Manuscript illumination search failed:', err);
            self.searchError(
                arches.translations.biblissimaNetworkError ||
                    'Network error while querying Biblissima',
            );
            self.searchResults([]);
            self.searching(false);
        }
    };

    this.searchManuscripts = async () => {
        const query = self.manuscriptQuery().trim();
        if (!query || query.length < 3) return;

        self.searching(true);
        self.hasSearched(true);
        self.currentPage(1);

        try {
            const resp = await fetch(`/api/biblissima/search-manuscripts?q=${encodeURIComponent(query)}`);
            const data = await resp.json();
            const results = (data.results || []).map(self._entityToItem);

            self.searchResults(results);
        } catch (err) {
            console.error('Biblissima manuscript search failed:', err);
            self.searchResults([]);
        }
        self.searching(false);
    };

    // =====================
    // COMPONENT MODE: search by iconographic descriptors
    // =====================
    this.selectedDescriptors = ko.observableArray();

    this.descriptorSelectConfig = {
        value: self.selectedDescriptors,
        clickBubble: true,
        multiple: true,
        closeOnSelect: true,
        allowClear: true,
        placeholder: arches.translations.biblissimaSearchDescriptors || 'Search iconographic descriptors...',
        minimumInputLength: 2,
        ajax: {
            url: '/api/biblissima/suggest',
            dataType: 'json',
            quietMillis: 300,
            data: (requestParams) => ({ q: requestParams.term || '', type: 'descriptor' }),
            processResults: (data) => ({
                results: (data.results || []).map((item) => ({
                    id: item.id,
                    text: item.label,
                    description: item.description,
                })),
            }),
        },
        templateResult: (item) => {
            if (!item.id) return item.text;
            let html = `<strong>${item.text}</strong>`;
            if (item.description) {
                html += `<br><small class="text-muted">${item.description}</small>`;
            }
            return html;
        },
        templateSelection: (item) => item.text,
        escapeMarkup: (m) => m,
    };

    this.searchComponents = async () => {
        const descriptors = self.selectedDescriptors();
        if (!descriptors || descriptors.length === 0) return;

        // Cancel any in-flight background page fetches from a previous search
        if (self._pageLoadAbort) {
            self._pageLoadAbort.abort();
        }
        const abortController = new AbortController();
        self._pageLoadAbort = abortController;

        self.searching(true);
        self.searchError(null);
        self.hasSearched(true);
        self.currentPage(1);
        self.searchResults([]);
        self.loadingProgress({
            loaded: 0,
            total: 0,
            loadedPages: 0,
            totalPages: 0,
        });

        const PAGE_SIZE = 50;

        try {
            const entityPromises = descriptors.map((qid) =>
                fetch(`/api/biblissima/entity/${qid}`).then((r) => r.json())
            );
            const entities = await Promise.all(entityPromises);
            // Use portal hashes for IIIF search.
            const hashes = entities.map((e) => e.portalHash).filter(Boolean);

            if (hashes.length === 0) {
                self.searchResults([]);
                self.searching(false);
                return;
            }

            const baseParams = new URLSearchParams({
                descriptors: hashes.join(','),
                page_size: String(PAGE_SIZE),
            });

            // --- Stage 1: blocking fetch of page 1 so we have something
            //              complete to show immediately ---
            const firstUrl = `/api/biblissima/search?${baseParams}&page=1`;
            const firstResp = await fetch(firstUrl, {
                signal: abortController.signal,
            });
            const firstData = await firstResp.json().catch(() => ({}));
            if (!firstResp.ok) {
                self.searchError(
                    firstData.message ||
                        arches.translations.biblissimaSearchFailed ||
                        'Biblissima search failed',
                );
                self.searchResults([]);
                self.searching(false);
                return;
            }

            const firstResults = firstData.results || [];
            self.searchResults(firstResults);
            self.searching(false); // page 1 visible — stop the global spinner

            const total = firstData.total || firstResults.length;
            const totalPages = firstData.total_pages || 1;
            self.loadingProgress({
                loaded: firstResults.length,
                total: total,
                loadedPages: 1,
                totalPages: totalPages,
            });

            // --- Stage 2: background, sequential load of pages 2..N ---
            for (let page = 2; page <= totalPages; page++) {
                if (abortController.signal.aborted) return;
                try {
                    const pageUrl = `/api/biblissima/search?${baseParams}&page=${page}`;
                    const pageResp = await fetch(pageUrl, {
                        signal: abortController.signal,
                    });
                    if (!pageResp.ok) continue;
                    const pageData = await pageResp.json();
                    const pageResults = pageData.results || [];

                    // Append the new page to searchResults (Knockout re-render)
                    const current = self.searchResults();
                    self.searchResults(current.concat(pageResults));
                    self.loadingProgress({
                        loaded: self.searchResults().length,
                        total: total,
                        loadedPages: page,
                        totalPages: totalPages,
                    });
                } catch (err) {
                    if (err.name === 'AbortError') return;
                    console.warn(`Biblissima page ${page} load failed`, err);
                }
            }
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('Biblissima search failed:', err);
            self.searchError(
                arches.translations.biblissimaNetworkError ||
                    'Network error while querying Biblissima',
            );
            self.searchResults([]);
            self.searching(false);
        }
    };

    // =====================
    // SHARED
    // =====================

    this.search = () => {
        self.searchError(null);
        if (self.isDocument) {
            self.searchManuscripts();
        } else if (self.componentSearchMode() === 'manuscript') {
            self.searchManuscriptIlluminations();
        } else {
            self.searchComponents();
        }
    };

    // Cart identity: pick the most-specific unique identifier on the
    // item. ``arkId`` is the **illumination** ARK in Component mode and
    // the **manuscript** ARK in Document mode — unique either way.
    // ``canvasId`` is unique per IIIF canvas (page-level, even more
    // specific). ``biblissimaQid`` is *manuscript-level* on enriched
    // illumination canvases (set in ``_enrich_canvases`` from the
    // resolved Wikibase entity), so it must NEVER be used to compare
    // two illuminations against each other — falling back to it would
    // make every illumination of the same manuscript look "selected"
    // after a single click. Only kept as a last-resort key for items
    // that genuinely lack an ARK / canvas (e.g. a manuscript added by
    // direct QID via ``addByIdentifier``).
    this._itemKey = (item) => {
        if (!item) return '';
        return String(item.arkId || item.canvasId || item.biblissimaQid || '');
    };
    this._sameItem = (a, b) => {
        const ka = self._itemKey(a);
        if (!ka) return false;
        return ka === self._itemKey(b);
    };

    this.isInCart = (item) =>
        ko.computed(() => self.cart().some((c) => self._sameItem(c, item)));

    this.toggleCartItem = (item) => {
        const existing = self.cart().find((c) => self._sameItem(c, item));
        if (existing) {
            self.cart.remove(existing);
        } else if (!self.cartIsFull()) {
            self.cart.push(item);
        }
    };

    this.removeFromCart = (item) => self.cart.remove(item);

    this.nextPage = () => {
        if (self.currentPage() < self.totalPages()) self.currentPage(self.currentPage() + 1);
    };

    this.prevPage = () => {
        if (self.currentPage() > 1) self.currentPage(self.currentPage() - 1);
    };

    // "Add all visible" is all-or-nothing: only enabled when every visible
    // item that isn't already in the cart fits within the remaining cap.
    // If the page would overflow the cap we keep the user in control —
    // they reduce the page size or unselect items rather than us silently
    // truncating the page (which would hide which items got dropped).
    this._addableFromVisible = ko.computed(() =>
        self.pagedResults().filter(
            (item) => !self.cart().some((c) => self._sameItem(c, item))
        )
    );
    this.canAddAllVisible = ko.computed(() => {
        const addable = self._addableFromVisible().length;
        if (addable === 0) return false;
        return self.cart().length + addable <= self.cartMax;
    });
    this.addAllVisibleTooltip = ko.computed(() => {
        if (self.cartIsFull()) return self.cartLimitLabel;
        const addable = self._addableFromVisible().length;
        if (addable === 0) return '';
        if (self.cart().length + addable > self.cartMax) {
            return self.cartAddAllTooManyLabel;
        }
        return '';
    });

    this.addAllVisible = () => {
        if (!self.canAddAllVisible()) return;
        self._addableFromVisible().forEach((item) => self.cart.push(item));
    };

    this.clearCart = () => self.cart.removeAll();

    // Auto-persistence: every cart/descriptor mutation flows to params.value
    // AND directly to workflow_history.componentdata. Bypasses the framework's
    // NonTileBasedComponent.save (which would force complete=true) so we keep
    // full control over complete = "user is allowed to advance".
    //
    // Debounced because addAllVisible() pushes up to N items via forEach,
    // firing N subscriber calls — we coalesce into one BDD write.
    let _persistTimer = null;
    const _persist = () => {
        const value = {
            selectedItems: ko.toJS(self.cart()),
            descriptors: ko.toJS(self.selectedDescriptors()),
        };
        params.value(value);
        if (params.form?.setToWorkflowHistory) {
            params.form.setToWorkflowHistory('value', value);
            // Mark as saved so the framework hides "Save and Continue" and
            // shows "Next Step" instead.
            params.form.savedData?.(value);
        }
    };
    const _schedulePersist = () => {
        if (_persistTimer) clearTimeout(_persistTimer);
        _persistTimer = setTimeout(() => {
            _persistTimer = null;
            _persist();
        }, 300);
    };
    self.cart.subscribe(_schedulePersist);
    self.selectedDescriptors.subscribe(_schedulePersist);

    // The workflow's "Next Step" button is disabled when required && !complete.
    // Cart must hold ≥ 1 item to advance to step 3.
    ko.computed(() => self.complete(self.cart().length > 0));

    this.dirty = ko.computed(() => self.cart().length > 0);

    // Initialize noUiSlider for date range (dual handles)
    this.initSlider = (element) => {
        if (self._slider) return;
        const slider = noUiSlider.create(element, {
            start: [self.dateFrom(), self.dateTo()],
            connect: true,
            step: 10,
            range: { min: DATE_MIN, max: DATE_MAX },
            behaviour: 'drag-tap',
            format: {
                to: (v) => Math.round(v),
                from: (v) => Number(v),
            },
        });

        let sliding = false;
        slider.on('slide', (values) => {
            sliding = true;
            self.dateFrom(values[0]);
            self.dateTo(values[1]);
            sliding = false;
        });

        self.dateFrom.subscribe((val) => {
            if (!sliding) slider.set([val, null]);
        });
        self.dateTo.subscribe((val) => {
            if (!sliding) slider.set([null, val]);
        });

        self._slider = slider;
    };

    this.initialize = () => {
        if (params.value()) {
            const cached = ko.unwrap(params.value);
            if (cached.selectedItems) self.cart(cached.selectedItems);
        }
    };

    this.initialize();
};

ko.components.register('biblissima-search-step', {
    viewModel: viewModel,
    template: biblissimaSearchStepTemplate,
});

export default viewModel;
