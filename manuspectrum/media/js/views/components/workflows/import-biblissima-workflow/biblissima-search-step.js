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
            // Determine if it's a QID (Q12345) or ARK
            let qid = id;
            if (id.startsWith('ark:')) {
                // Search by portal hash — extract hash and search
                const hash = id.replace('ark:/43093/', '');
                const resp = await fetch(`/api/biblissima/suggest?q=${encodeURIComponent(hash)}&limit=5`);
                const data = await resp.json();
                if (data.results?.length > 0) {
                    qid = data.results[0].id;
                } else {
                    console.warn('No Wikibase entity found for ARK:', id);
                    self.addingDirect(false);
                    return;
                }
            }

            // Fetch entity details
            const resp = await fetch(`/api/biblissima/entity/${qid}`);
            if (!resp.ok) {
                console.warn('Entity not found:', qid);
                self.addingDirect(false);
                return;
            }
            const d = await resp.json();
            const item = self._entityToItem(d);

            // Add to cart if not already there
            const exists = self.cart().some(
                (c) => c.biblissimaQid === item.biblissimaQid
            );
            if (!exists) {
                self.cart.push(item);
            }
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

    this.searchManuscripts = async () => {
        const query = self.manuscriptQuery().trim();
        if (!query || query.length < 3) return;

        self.searching(true);
        self.hasSearched(true);
        self.currentPage(1);

        try {
            const suggestType = self.isDocument ? 'manuscript' : 'descriptor';
            const resp = await fetch(`/api/biblissima/suggest?q=${encodeURIComponent(query)}&limit=${self.pageSize()}&type=${suggestType}`);
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
            const hashes = entities.map((e) => e.portalHash).filter(Boolean);

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
                page_size: self.pageSize(),
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
