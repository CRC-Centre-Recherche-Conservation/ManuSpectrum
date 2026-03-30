import ko from 'knockout';
import arches from 'arches';
import biblissimaCreateStepTemplate from 'templates/views/components/workflows/import-biblissima-workflow/biblissima-create-step.htm';

const viewModel = function(params) {
    const self = this;

    // Workflow step interface
    this.complete = params.form?.complete || ko.observable(false);
    this.saving = ko.observable(false);
    this.loading = ko.observable(true);

    // Config from step 1
    this.config = params.configStepData || {};
    this.resourceType = this.config.resourceType || 'Document';
    this.parentDocumentId = this.config.parentDocumentId || null;
    this.projectId = this.config.projectId || null;
    this.defaultType = this.config.defaultType || null;

    // Items from step 2
    this.searchData = params.searchStepData || {};
    this.selectedItems = ko.observableArray(this.searchData.selectedItems || []);

    // Dependencies resolution
    this.dependencies = ko.observableArray();
    this.dependenciesResolved = ko.observable(false);

    // Items with status tracking
    this.items = ko.observableArray();
    this.creatingAll = ko.observable(false);

    // Stats
    this.createdCount = ko.computed(() =>
        self.items().filter((i) => i.status() === 'created').length
    );
    this.linkedCount = ko.computed(() =>
        self.items().filter((i) => i.status() === 'linked').length
    );
    this.totalCount = ko.computed(() => self.items().length);
    this.allDone = ko.computed(() =>
        self.totalCount() > 0 && self.items().every(
            (i) => i.status() === 'created' || i.status() === 'linked' || i.status() === 'skipped'
        )
    );

    // Dependency cache (shared across creations)
    this.dependencyCache = {
        places: {},
        persons: {},
        groups: {},
    };

    // Initialize items with status observables
    this.initializeItems = () => {
        const items = (self.searchData.selectedItems || []).map((item) => ({
            ...item,
            // pending | creating | created | error | linked
            status: ko.observable('pending'),
            resourceId: ko.observable(null),
            errorMessage: ko.observable(''),
            // Duplicate suggestions
            suggestions: ko.observableArray([]),
            showSuggestions: ko.observable(false),
            // Linked to existing resource
            linkedResourceId: ko.observable(null),
            linkedDisplayname: ko.observable(''),
            enrichExisting: ko.observable(true),  // checkbox: enrich with Biblissima data
        }));
        self.items(items);
    };

    // Check for potential duplicates using flexible matching
    this.checkDuplicates = async () => {
        const graphId = self.resourceType === 'Document'
            ? '0c8226c1-11a9-4c48-9601-a7a0c6f2df6b'
            : 'd47595b4-f8a6-419c-8f33-b388206280c4';

        const checkItems = self.items().map((i) => ({
            arkId: i.arkId || '',
            label: i.label || i.legend || '',
            shelfmark: i.shelfmark || '',
            biblissimaQid: i.biblissimaQid || '',
            portalHash: (i.arkId || '').replace('ark:/43093/', ''),
            manifestUrl: i.manifestUrl || '',
        }));

        try {
            const resp = await fetch('/api/biblissima/check-duplicates', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': self.getCSRFToken(),
                },
                body: JSON.stringify({ items: checkItems, graphId }),
            });
            const data = await resp.json();
            const results = data.results || [];

            results.forEach((result) => {
                const item = self.items()[result.index];
                if (item && result.suggestions.length > 0) {
                    item.suggestions(result.suggestions);
                    item.showSuggestions(true);
                }
            });
        } catch (err) {
            console.error('Duplicate check failed:', err);
        }
        self.loading(false);
    };

    // User confirms: not a duplicate, create anyway
    this.dismissSuggestions = (item) => {
        item.showSuggestions(false);
        item.suggestions([]);
    };

    // User confirms: use existing resource instead
    this.useExisting = (item, suggestion) => {
        item.status('linked');
        item.linkedResourceId(suggestion.resourceId);
        item.linkedDisplayname(suggestion.displayname || '');
        item.resourceId(suggestion.resourceId);
        item.showSuggestions(false);
    };

    // Unlink: go back to pending
    this.unlinkItem = (item) => {
        item.status('pending');
        item.linkedResourceId(null);
        item.linkedDisplayname('');
        item.resourceId(null);
        item.showSuggestions(true);
    };

    // View a suggested match in new tab
    this.viewSuggestion = (suggestion) => {
        window.open(`/resource/${suggestion.resourceId}`, '_blank');
    };

    // Graph IDs for dependency types
    const PLACE_GRAPH_ID = '3f2b036a-b65d-474d-b692-0b21903655c5';
    const PERSON_GRAPH_ID = '5bf45c85-84cd-4a76-b64a-3ffe86eea1b8';
    const GROUP_GRAPH_ID = '4f447dca-dbb3-48d0-bc90-3f2935db8b8c';

    // Resolve dependencies: extract unique Places, Groups, Persons from items
    // then search Arches to find existing matches
    this.resolveDependencies = async () => {
        const deps = [];
        const seen = new Set();

        self.items().forEach((item) => {
            // Place (current location from collection)
            const location = item.locationLabel || item.location;
            if (location && location !== 'Origine inconnue' && !seen.has(`place:${location}`)) {
                seen.add(`place:${location}`);
                deps.push({
                    key: location,
                    type: 'Place',
                    graphId: PLACE_GRAPH_ID,
                    label: ko.observable(location),
                    action: ko.observable('search'),  // searching...
                    existingId: ko.observable(null),
                    existingLabel: ko.observable(''),
                    suggestions: ko.observableArray([]),
                });
            }

            // Group (owner / collection)
            const owner = item.collectionLabel;
            if (owner && !seen.has(`group:${owner}`)) {
                seen.add(`group:${owner}`);
                deps.push({
                    key: owner,
                    type: 'Group',
                    graphId: GROUP_GRAPH_ID,
                    label: ko.observable(owner),
                    action: ko.observable('search'),
                    existingId: ko.observable(null),
                    existingLabel: ko.observable(''),
                    suggestions: ko.observableArray([]),
                });
            }

            // Parent institution (top-level Group)
            const parentInst = item.parentInstitutionLabel;
            if (parentInst && parentInst !== owner && !seen.has(`group:${parentInst}`)) {
                seen.add(`group:${parentInst}`);
                deps.push({
                    key: parentInst,
                    type: 'Group',
                    graphId: GROUP_GRAPH_ID,
                    label: ko.observable(parentInst),
                    action: ko.observable('search'),
                    existingId: ko.observable(null),
                    existingLabel: ko.observable(''),
                    suggestions: ko.observableArray([]),
                });
            }

            // Author (Person)
            const author = item.authorLabel;
            if (author && !seen.has(`person:${author}`)) {
                seen.add(`person:${author}`);
                deps.push({
                    key: author,
                    type: 'Person',
                    graphId: PERSON_GRAPH_ID,
                    label: ko.observable(author),
                    action: ko.observable('search'),
                    existingId: ko.observable(null),
                    existingLabel: ko.observable(''),
                    suggestions: ko.observableArray([]),
                });
            }
        });

        self.dependencies(deps);

        // Search Arches for existing matches for each dependency
        for (const dep of deps) {
            try {
                const resp = await fetch('/api/biblissima/check-duplicates', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': self.getCSRFToken(),
                    },
                    body: JSON.stringify({
                        items: [{ label: dep.key, shelfmark: '', arkId: '', biblissimaQid: '' }],
                        graphId: dep.graphId,
                    }),
                });
                const data = await resp.json();
                const result = data.results?.[0];
                if (result?.suggestions?.length > 0) {
                    dep.suggestions(result.suggestions);
                    // Auto-select first high-confidence match
                    const best = result.suggestions.find((s) => s.confidence === 'high');
                    if (best) {
                        dep.action('use_existing');
                        dep.existingId(best.resourceId);
                        dep.existingLabel(best.displayname);
                    } else {
                        dep.action('create');
                    }
                } else {
                    dep.action('create');
                }
            } catch (err) {
                console.warn('Dependency search failed for:', dep.key, err);
                dep.action('create');
            }
        }

        self.dependenciesResolved(true);
    };

    // Build a Select2 config for a dependency picker (search existing resources)
    this.buildDepPickerConfig = (dep) => {
        const selectedValue = ko.observable(null);
        selectedValue.subscribe((val) => {
            if (val && typeof val === 'string' && val.length > 10) {
                // Fetch the displayname
                fetch(`${arches.urls.api_resources(val)}?format=json&compact=false&v=beta`)
                    .then((r) => r.ok ? r.json() : null)
                    .then((data) => {
                        dep.existingId(val);
                        dep.existingLabel(data?.displayname || val);
                        dep.action('use_existing');
                    })
                    .catch(() => {
                        dep.existingId(val);
                        dep.existingLabel(val);
                        dep.action('use_existing');
                    });
            }
        });

        return {
            value: selectedValue,
            clickBubble: true,
            multiple: false,
            closeOnSelect: true,
            allowClear: true,
            placeholder: arches.translations.biblissimaSearchExisting || 'Search existing resource...',
            minimumInputLength: 2,
            ajax: {
                url: arches.urls.search_results,
                dataType: 'json',
                quietMillis: 250,
                data: (requestParams) => {
                    const params = {
                        'paging-filter': 1,
                        'resource-type-filter': JSON.stringify([
                            { graphid: dep.graphId, inverted: false }
                        ]),
                    };
                    if (requestParams.term) {
                        params['term-filter'] = JSON.stringify([{
                            context: '', context_label: '', id: 0,
                            text: requestParams.term, type: 'term',
                            value: requestParams.term, inverted: false,
                        }]);
                    }
                    return params;
                },
                processResults: (data) => {
                    const hits = data?.results?.hits?.hits || [];
                    return {
                        results: hits.map((hit) => ({
                            id: hit._id,
                            text: hit._source?.displayname || hit._id,
                        })).filter((r) => r.text && r.text !== 'Undefined'),
                    };
                },
            },
            templateResult: (item) => item.text || '',
            templateSelection: (item) => item.text || '',
            escapeMarkup: (m) => m,
        };
    };

    // Create a single resource
    this.createResource = async (item) => {
        if (item.status() === 'created' || item.status() === 'skipped') return;

        item.status('creating');

        // Resolve dependencies for this item
        const deps = {
            project: self.projectId,
            parentDocument: self.parentDocumentId,
        };

        // Find place dependency
        const placeDep = self.dependencies().find(
            (d) => d.type === 'Place' && d.key === item.location
        );
        if (placeDep && placeDep.action() === 'use_existing' && placeDep.existingId()) {
            deps.productionPlace = placeDep.existingId();
        }

        // Find person dependency (author)
        const personDep = self.dependencies().find(
            (d) => d.type === 'Person' && d.key === item.authorLabel
        );
        if (personDep && personDep.action() === 'use_existing' && personDep.existingId()) {
            deps.productionActors = [personDep.existingId()];
        }

        const body = {
            resourceType: self.resourceType,
            transactionId: null,
            biblissimaData: item,
            dependencies: deps,
            conceptMappings: {
                type: self.defaultType,
            },
        };

        try {
            const resp = await fetch('/api/biblissima/create-resource', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': self.getCSRFToken(),
                },
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Creation failed');
            }

            const data = await resp.json();
            item.resourceId(data.resourceId);
            item.status('created');

            // Update dependency cache with created dependencies
            if (data.createdDependencies) {
                Object.assign(self.dependencyCache.places, data.createdDependencies.places || {});
                Object.assign(self.dependencyCache.persons, data.createdDependencies.persons || {});
                Object.assign(self.dependencyCache.groups, data.createdDependencies.groups || {});
            }
        } catch (err) {
            item.status('error');
            item.errorMessage(err.message || 'Unknown error');
            console.error('Resource creation failed:', err);
        }
    };

    // Create all pending items
    this.createAll = async () => {
        self.creatingAll(true);
        const pendingItems = self.items().filter(
            (i) => i.status() === 'pending'
        );

        for (const item of pendingItems) {
            await self.createResource(item);
        }
        self.creatingAll(false);
    };

    // Skip a duplicate item
    this.skipItem = (item) => {
        item.status('skipped');
    };

    // Open resource in Arches editor (new tab)
    this.editResource = (item) => {
        if (item.resourceId()) {
            window.open(`/resource/${item.resourceId()}`, '_blank');
        }
    };

    // Open existing duplicate resource
    this.viewDuplicate = (item) => {
        if (item.duplicateResourceId()) {
            window.open(`/resource/${item.duplicateResourceId()}`, '_blank');
        }
    };

    // Force create even if duplicate
    this.forceCreate = (item) => {
        item.status('pending');
        item.duplicateResourceId(null);
        self.createResource(item);
    };

    // Refresh item data from API after editing
    this.refreshItem = async (item) => {
        if (!item.resourceId()) return;
        try {
            const resp = await fetch(
                `${arches.urls.api_resources(item.resourceId())}?format=json&compact=false&v=beta`
            );
            if (resp.ok) {
                const data = await resp.json();
                // Update display name
                if (data.displayname) {
                    item.label = data.displayname;
                    self.items.valueHasMutated();
                }
            }
        } catch (err) {
            console.warn('Failed to refresh item:', err);
        }
    };

    // Listen for window focus to refresh edited items
    this._focusHandler = () => {
        self.items().forEach((item) => {
            if (item.status() === 'created' && item.resourceId()) {
                self.refreshItem(item);
            }
        });
    };
    window.addEventListener('focus', this._focusHandler);

    // Cleanup
    this.dispose = () => {
        window.removeEventListener('focus', self._focusHandler);
    };

    // Submit (go to summary)
    this.submit = () => {
        const created = self.items().filter((i) => i.status() === 'created');
        const linked = self.items().filter((i) => i.status() === 'linked');

        params.value({
            createdResources: created.map((i) => ({
                resourceId: i.resourceId(),
                label: i.label || i.legend || '',
                arkId: i.arkId,
                manuscript: i.manuscript,
            })),
            linkedResources: linked.map((i) => ({
                resourceId: i.linkedResourceId(),
                displayname: i.linkedDisplayname(),
                biblissimaLabel: i.label || i.legend || '',
                arkId: i.arkId,
                biblissimaQid: i.biblissimaQid || '',
                manifestUrl: i.manifestUrl || '',
                shelfmark: i.shelfmark || '',
                enrichExisting: i.enrichExisting(),
            })),
            skippedCount: self.items().filter((i) => i.status() === 'skipped').length,
            errorCount: self.items().filter((i) => i.status() === 'error').length,
            resourceType: self.resourceType,
            projectId: self.projectId,
        });
        self.complete(true);
    };

    // CSRF token helper
    this.getCSRFToken = () => {
        const cookie = document.cookie.split(';').find((c) => c.trim().startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : '';
    };

    // Status CSS class
    this.statusClass = (status) => {
        const map = {
            pending: '',
            creating: 'info',
            created: 'success',
            linked: 'linked',
            error: 'danger',
            skipped: 'warning',
            duplicate: 'warning',
        };
        return map[status] || '';
    };

    // Status label
    this.statusLabel = (status) => {
        const map = {
            pending: arches.translations.biblissimaPending || 'Pending',
            creating: arches.translations.biblissimaCreating || 'Creating...',
            created: arches.translations.biblissimaCreated || 'Created',
            linked: arches.translations.biblissimaLinked || 'Linked',
            error: arches.translations.biblissimaError || 'Error',
            skipped: arches.translations.biblissimaSkipped || 'Skipped',
            duplicate: arches.translations.biblissimaDuplicate || 'Duplicate',
        };
        return map[status] || status;
    };

    // Initialize
    this.initializeItems();
    this.resolveDependencies();
    this.checkDuplicates();
};

ko.components.register('biblissima-create-step', {
    viewModel: viewModel,
    template: biblissimaCreateStepTemplate,
});

export default viewModel;
