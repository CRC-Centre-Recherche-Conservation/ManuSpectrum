import ko from 'knockout';
import arches from 'arches';
import 'bindings/select2-query';
import biblissimaSearchStepTemplate from 'templates/views/components/workflows/import-biblissima-workflow/biblissima-search-step.htm';

const viewModel = function(params) {
    const self = this;

    // Workflow step interface
    this.complete = params.form?.complete || ko.observable(false);
    this.saving = ko.observable(false);
    this.loading = ko.observable(false);

    // Search state
    this.selectedDescriptors = ko.observableArray();
    this.dateFilter = ko.observable('');
    this.searchResults = ko.observableArray();
    this.totalResults = ko.observable(0);
    this.currentPage = ko.observable(1);
    this.totalPages = ko.observable(0);
    this.hasSearched = ko.observable(false);

    // Cart (panier)
    this.cart = ko.observableArray();

    this.cartCount = ko.computed(() => self.cart().length);

    // Descriptor search config (Select2 multi-tag)
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
            data: (requestParams) => ({ q: requestParams.term || '' }),
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

    // Century filter options
    this.centuryOptions = [
        { value: '', label: arches.translations.biblissimaAllDates || 'All dates' },
        { value: '401-500', label: 'Ve' },
        { value: '501-600', label: 'VIe' },
        { value: '601-700', label: 'VIIe' },
        { value: '701-800', label: 'VIIIe' },
        { value: '801-900', label: 'IXe' },
        { value: '901-1000', label: 'Xe' },
        { value: '1001-1100', label: 'XIe' },
        { value: '1101-1200', label: 'XIIe' },
        { value: '1201-1300', label: 'XIIIe' },
        { value: '1301-1400', label: 'XIVe' },
        { value: '1401-1500', label: 'XVe' },
        { value: '1501-1600', label: 'XVIe' },
        { value: '1601-1700', label: 'XVIIe' },
        { value: '1701-1800', label: 'XVIIIe' },
    ];

    // Check if an item is in the cart
    this.isInCart = (item) => {
        return ko.computed(() =>
            self.cart().some((c) => c.arkId === item.arkId || c.canvasId === item.canvasId)
        );
    };

    // Toggle item in cart
    this.toggleCartItem = (item) => {
        const existing = self.cart().find(
            (c) => c.arkId === item.arkId || c.canvasId === item.canvasId
        );
        if (existing) {
            self.cart.remove(existing);
        } else {
            self.cart.push(item);
        }
    };

    // Remove from cart
    this.removeFromCart = (item) => {
        self.cart.remove(item);
    };

    // Search Biblissima
    this.search = (page) => {
        const descriptors = self.selectedDescriptors();
        if (!descriptors || descriptors.length === 0) return;

        self.loading(true);
        self.hasSearched(true);
        const pageNum = page || 1;
        self.currentPage(pageNum);

        // We need the portal hashes for each descriptor
        // First fetch entity details to get P129 hashes
        const entityPromises = descriptors.map((qid) =>
            fetch(`/api/biblissima/entity/${qid}`).then((r) => r.json())
        );

        Promise.all(entityPromises)
            .then((entities) => {
                const hashes = entities
                    .map((e) => e.portalHash)
                    .filter(Boolean);

                if (hashes.length === 0) {
                    self.searchResults([]);
                    self.totalResults(0);
                    self.totalPages(0);
                    self.loading(false);
                    return;
                }

                const params = new URLSearchParams({
                    descriptors: hashes.join(','),
                    page: pageNum,
                    page_size: 20,
                });
                if (self.dateFilter()) {
                    params.set('date', self.dateFilter());
                }

                return fetch(`/api/biblissima/search?${params}`)
                    .then((r) => r.json())
                    .then((data) => {
                        self.searchResults(data.results || []);
                        self.totalResults(data.total || 0);
                        self.totalPages(data.totalPages || 0);
                    });
            })
            .catch((err) => {
                console.error('Biblissima search failed:', err);
                self.searchResults([]);
            })
            .finally(() => {
                self.loading(false);
            });
    };

    // Pagination
    this.nextPage = () => {
        if (self.currentPage() < self.totalPages()) {
            self.search(self.currentPage() + 1);
        }
    };

    this.prevPage = () => {
        if (self.currentPage() > 1) {
            self.search(self.currentPage() - 1);
        }
    };

    // Add all visible results to cart
    this.addAllVisible = () => {
        self.searchResults().forEach((item) => {
            const exists = self.cart().some(
                (c) => c.arkId === item.arkId || c.canvasId === item.canvasId
            );
            if (!exists) {
                self.cart.push(item);
            }
        });
    };

    // Clear cart
    this.clearCart = () => {
        self.cart.removeAll();
    };

    // Submit
    this.submit = () => {
        if (self.cart().length === 0) return;
        self.saving(true);
        params.value({
            selectedItems: ko.toJS(self.cart()),
            descriptors: ko.toJS(self.selectedDescriptors()),
        });
        self.saving(false);
        self.complete(true);
    };

    // Dirty tracking
    this.dirty = ko.computed(() => self.cart().length > 0);

    // Restore from cached value
    this.initialize = () => {
        if (params.value()) {
            const cached = ko.unwrap(params.value);
            if (cached.selectedItems) {
                self.cart(cached.selectedItems);
            }
        }
    };

    this.stripTags = (original) => original?.replace(/(<([^>]+)>)/gi, '') || '';

    this.initialize();
};

ko.components.register('biblissima-search-step', {
    viewModel: viewModel,
    template: biblissimaSearchStepTemplate,
});

export default viewModel;
