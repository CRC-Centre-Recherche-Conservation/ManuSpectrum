import ko from 'knockout';
import arches from 'arches';
import 'bindings/select2-query';
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

    // Config from step 1
    this.config = params.configStepData || {};
    this.resourceType = this.config.resourceType || 'Document';
    this.isDocument = this.resourceType === 'Document';
    this.isComponent = this.resourceType === 'Component';

    // Component search mode: 'descriptor' (IIIF search) or 'manuscript' (portal scraping)
    this.componentSearchMode = ko.observable('descriptor');

    // Search state
    this.searchResults = ko.observableArray();
    this.totalResults = ko.observable(0);
    this.currentPage = ko.observable(1);
    this.totalPages = ko.observable(0);
    this.hasSearched = ko.observable(false);

    // Cart
    this.cart = ko.observableArray();
    this.cartCount = ko.computed(() => self.cart().length);

    // =====================
    // SHARED: filters panel (collapsible)
    // =====================
    this.showFilters = ko.observable(false);
    this.toggleFilters = () => self.showFilters(!self.showFilters());
    this.pageSize = ko.observable('20');
    // Effective limit: 0 means "all" → use a large number for API calls
    this.effectiveLimit = ko.computed(() => {
        const val = parseInt(self.pageSize(), 10);
        return val === 0 ? 500 : val;
    });

    // Date range slider
    this.dateFrom = ko.observable(DATE_MIN);
    this.dateTo = ko.observable(DATE_MAX);
    // dateRangeActive kept for getDateParam — always active when dates differ from extremes
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

    // Build Biblissima date param from range
    this.getDateParam = () => {
        if (!self.dateRangeActive()) return '';
        return `${self.dateFrom()}-${self.dateTo()}`;
    };

    // Direct identifier input (QID or ARK)
    this.directIdentifier = ko.observable('');
    this.addingDirect = ko.observable(false);

    this.addByIdentifier = async () => {
        const id = self.directIdentifier().trim();
        if (!id) return;

        self.addingDirect(true);
        try {
            // Handle ifdata ARK (illumination) — add directly as component item
            if (id.includes('ifdata')) {
                const hash = id.replace('ark:/43093/', '').replace(/.*ifdata/, 'ifdata');
                const resp = await fetch(`/api/biblissima/illumination/${hash}`);
                if (resp.ok) {
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
                        biblissimaQid: '',
                        shelfmark: '',
                        collectionLabel: '',
                        locationLabel: '',
                        locationQid: '',
                        geonamesId: '',
                        parentInstitutionLabel: '',
                        parentInstitutionQid: '',
                        authorLabel: '',
                        authorQid: '',
                        mandragoreId: '',
                        digitizationUrl: '',
                        hasImage: !!detail.imageUrl,
                        typeValueId: detail.typeValueId || '',
                        ifdataHash: detail.ifdataHash,
                        mandragoreArk: detail.mandragoreArk || '',
                    };
                    const exists = self.cart().some((c) => c.arkId === item.arkId);
                    if (!exists) self.cart.push(item);
                    self.directIdentifier('');
                }
                self.addingDirect(false);
                return;
            }

            // Handle QID or mdata ARK
            let qid = id;
            if (id.startsWith('ark:') || id.startsWith('mdata')) {
                // It's a manuscript ARK — in Component mode, load its illuminations
                const hash = id.replace('ark:/43093/', '');
                if (self.isComponent) {
                    self.selectedManuscriptHash(hash);
                    self.componentSearchMode('manuscript');
                    // Fetch illuminations for this manuscript
                    const illumResp = await fetch(`/api/biblissima/manuscript-illuminations?portalHash=${hash}`);
                    const illumData = await illumResp.json();
                    if (illumData.results?.length > 0) {
                        self.searchResults(illumData.results.map((item) => ({
                            canvasId: item.ifdataHash,
                            arkId: item.arkId,
                            label: item.label,
                            thumbnail: null,
                            manuscript: '',
                            folio: item.folio,
                            legend: item.descriptor,
                            date: '',
                            location: '',
                            descriptors: [item.descriptor],
                            portalUrl: item.portalUrl,
                            manifestUrl: '',
                            biblissimaQid: '',
                            shelfmark: '',
                            collectionLabel: '',
                            locationLabel: '',
                            locationQid: '',
                            geonamesId: '',
                            parentInstitutionLabel: '',
                            parentInstitutionQid: '',
                            authorLabel: '',
                            authorQid: '',
                            mandragoreId: '',
                            digitizationUrl: '',
                            hasImage: item.hasImage,
                            typeValueId: item.typeValueId || '',
                            ifdataHash: item.ifdataHash,
                        })));
                        self.totalResults(illumData.results.length);
                        self.hasSearched(true);
                    }
                    self.directIdentifier('');
                    self.addingDirect(false);
                    return;
                }
                // In Document mode, try to find the QID
                const resp = await fetch(`/api/biblissima/suggest?q=${encodeURIComponent(hash)}&limit=5`);
                const data = await resp.json();
                if (data.results?.length > 0) {
                    qid = data.results[0].id;
                } else {
                    self.addingDirect(false);
                    return;
                }
            }

            // Fetch entity details (for QID)
            const resp = await fetch(`/api/biblissima/entity/${qid}`);
            if (!resp.ok) {
                self.addingDirect(false);
                return;
            }
            const d = await resp.json();

            // In Component mode: if this is a manuscript, load its illuminations
            if (self.isComponent && d.portalHash && d.portalHash.startsWith('mdata')) {
                self.manuscriptForComponent(d.label || qid);
                self.searchManuscriptIlluminations();
                self.directIdentifier('');
                self.addingDirect(false);
                return;
            }

            // In Document mode: add as document
            const item = self._entityToItem(d);
            const exists = self.cart().some((c) => c.biblissimaQid === item.biblissimaQid);
            if (!exists) self.cart.push(item);
            self.directIdentifier('');
        } catch (err) {
            console.error('Failed to add by identifier:', err);
        }
        self.addingDirect(false);
    };

    // =====================
    // DOCUMENT MODE: search by manuscript name/shelfmark
    // =====================
    this.manuscriptQuery = ko.observable('');

    this._entityToItem = (d) => ({
        canvasId: d.qid,
        arkId: d.portalHash ? `ark:/43093/${d.portalHash}` : null,
        label: d.label || '',
        thumbnail: null,
        manuscript: d.shelfmark || d.label || '',
        folio: '',
        legend: d.label || '',
        date: '',
        location: d.locationLabel || '',
        descriptors: [],
        portalUrl: d.portalHash ? `https://portail.biblissima.fr/ark:/43093/${d.portalHash}` : '',
        manifestUrl: d.manifestUrl || '',
        authorLabel: d.authorLabel || '',
        authorQid: d.authorQid || '',
        biblissimaQid: d.qid || '',
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

    this.searchManuscriptIlluminations = async () => {
        const query = self.manuscriptForComponent().trim();
        if (!query) return;

        self.searching(true);
        self.hasSearched(true);

        try {
            let entityData;

            // If query looks like a QID (Q + digits), fetch entity directly
            if (/^Q\d+$/i.test(query)) {
                const entityResp = await fetch(`/api/biblissima/entity/${query}`);
                if (!entityResp.ok) { self.searching(false); return; }
                entityData = await entityResp.json();
            } else {
                // Search by text
                const suggestResp = await fetch(`/api/biblissima/suggest?q=${encodeURIComponent(query)}&limit=10&type=manuscript`);
                const suggestData = await suggestResp.json();
                if (!suggestData.results?.length) {
                    self.searchResults([]);
                    self.totalResults(0);
                    self.searching(false);
                    return;
                }
                const entityResp = await fetch(`/api/biblissima/entity/${suggestData.results[0].id}`);
                entityData = await entityResp.json();
            }

            const portalHash = entityData.portalHash;

            if (!portalHash) {
                self.searchResults([]);
                self.totalResults(0);
                self.searching(false);
                return;
            }

            self.selectedManuscriptLabel(entityData.label || firstResult.label);
            self.selectedManuscriptHash(portalHash);

            // Step 2: Get illuminations from portal page
            const illumResp = await fetch(`/api/biblissima/manuscript-illuminations?portalHash=${portalHash}`);
            const illumData = await illumResp.json();

            const results = (illumData.results || []).map((item) => ({
                canvasId: item.ifdataHash,
                arkId: item.arkId,
                label: item.label,
                thumbnail: null,
                manuscript: self.selectedManuscriptLabel(),
                folio: item.folio,
                legend: item.descriptor,
                date: '',
                location: '',
                descriptors: [item.descriptor],
                portalUrl: item.portalUrl,
                manifestUrl: entityData.manifestUrl || '',
                authorLabel: entityData.authorLabel || '',
                authorQid: entityData.authorQid || '',
                biblissimaQid: entityData.qid || '',
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
                ifdataHash: item.ifdataHash,
            }));

            self.searchResults(results);
            self.totalResults(results.length);
            self.totalPages(1);
        } catch (err) {
            console.error('Manuscript illumination search failed:', err);
            self.searchResults([]);
        }
        self.searching(false);
    };

    this.searchManuscripts = async () => {
        const query = self.manuscriptQuery().trim();
        if (!query || query.length < 3) return;

        self.searching(true);
        self.hasSearched(true);
        self.currentPage(1);

        try {
            const suggestType = self.isDocument ? 'manuscript' : 'descriptor';
            const resp = await fetch(`/api/biblissima/suggest?q=${encodeURIComponent(query)}&limit=${self.effectiveLimit()}&type=${suggestType}`);
            const data = await resp.json();
            const entities = data.results || [];

            const detailPromises = entities.map((e) =>
                fetch(`/api/biblissima/entity/${e.id}`)
                    .then((r) => r.json())
                    .catch(() => null)
            );

            const details = await Promise.all(detailPromises);
            const results = details.filter(Boolean).map(self._entityToItem);

            self.searchResults(results);
            self.totalResults(results.length);
            self.totalPages(1);
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

    this.searchComponents = async (page) => {
        const descriptors = self.selectedDescriptors();
        if (!descriptors || descriptors.length === 0) return;

        self.searching(true);
        self.hasSearched(true);
        const pageNum = page || 1;
        self.currentPage(pageNum);

        try {
            const entityPromises = descriptors.map((qid) =>
                fetch(`/api/biblissima/entity/${qid}`).then((r) => r.json())
            );
            const entities = await Promise.all(entityPromises);
            // Use portal hashes for IIIF search
            // For single descriptors, backend uses ARK format which works with any prefix (desc, pdata, etc.)
            // For multiple descriptors, backend uses AND| query format
            const hashes = entities
                .map((e) => e.portalHash)
                .filter(Boolean);

            if (hashes.length === 0) {
                self.searchResults([]);
                self.totalResults(0);
                self.totalPages(0);
                self.searching(false);
                return;
            }

            const searchParams = new URLSearchParams({
                descriptors: hashes.join(','),
                page: pageNum,
                page_size: self.effectiveLimit(),
            });
            const dateParam = self.getDateParam();
            if (dateParam) {
                searchParams.set('date', dateParam);
            }

            const resp = await fetch(`/api/biblissima/search?${searchParams}`);
            const data = await resp.json();
            self.searchResults(data.results || []);
            self.totalResults(data.total || 0);
            self.totalPages(data.totalPages || 0);
        } catch (err) {
            console.error('Biblissima search failed:', err);
            self.searchResults([]);
        }
        self.searching(false);
    };

    // =====================
    // SHARED
    // =====================

    this.search = (page) => {
        if (self.isDocument) {
            self.searchManuscripts();
        } else if (self.componentSearchMode() === 'manuscript') {
            self.searchManuscriptIlluminations();
        } else {
            self.searchComponents(page);
        }
    };

    this.isInCart = (item) =>
        ko.computed(() =>
            self.cart().some((c) =>
                (c.arkId && c.arkId === item.arkId) ||
                (c.canvasId && c.canvasId === item.canvasId) ||
                (c.biblissimaQid && c.biblissimaQid === item.biblissimaQid)
            )
        );

    this.toggleCartItem = (item) => {
        const existing = self.cart().find(
            (c) =>
                (c.arkId && c.arkId === item.arkId) ||
                (c.canvasId && c.canvasId === item.canvasId) ||
                (c.biblissimaQid && c.biblissimaQid === item.biblissimaQid)
        );
        if (existing) {
            self.cart.remove(existing);
        } else {
            self.cart.push(item);
        }
    };

    this.removeFromCart = (item) => self.cart.remove(item);

    this.nextPage = () => {
        if (self.currentPage() < self.totalPages()) self.search(self.currentPage() + 1);
    };

    this.prevPage = () => {
        if (self.currentPage() > 1) self.search(self.currentPage() - 1);
    };

    this.addAllVisible = () => {
        self.searchResults().forEach((item) => {
            const exists = self.cart().some(
                (c) =>
                    (c.arkId && c.arkId === item.arkId) ||
                    (c.canvasId && c.canvasId === item.canvasId) ||
                    (c.biblissimaQid && c.biblissimaQid === item.biblissimaQid)
            );
            if (!exists) self.cart.push(item);
        });
    };

    this.clearCart = () => self.cart.removeAll();

    this.submit = () => {
        if (self.cart().length === 0) return;
        params.value({
            selectedItems: ko.toJS(self.cart()),
            descriptors: ko.toJS(self.selectedDescriptors()),
        });
        self.complete(true);
    };

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
