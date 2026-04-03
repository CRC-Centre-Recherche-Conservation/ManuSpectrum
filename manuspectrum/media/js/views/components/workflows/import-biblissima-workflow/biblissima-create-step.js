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

    // Graph IDs for dependency types
    const PLACE_GRAPH_ID = '3f2b036a-b65d-474d-b692-0b21903655c5';
    const PERSON_GRAPH_ID = '5bf45c85-84cd-4a76-b64a-3ffe86eea1b8';
    const GROUP_GRAPH_ID = '4f447dca-dbb3-48d0-bc90-3f2935db8b8c';

    const DEP_TYPE_MAP = {
        Place: { graphId: PLACE_GRAPH_ID, cacheKey: 'places' },
        Group: { graphId: GROUP_GRAPH_ID, cacheKey: 'groups' },
        Person: { graphId: PERSON_GRAPH_ID, cacheKey: 'persons' },
    };

    // =============================================
    // Items
    // =============================================

    this.initializeItems = () => {
        const items = (self.searchData.selectedItems || []).map((item) => ({
            ...item,
            status: ko.observable('pending'),
            resourceId: ko.observable(null),
            errorMessage: ko.observable(''),
            suggestions: ko.observableArray([]),
            showSuggestions: ko.observable(false),
            linkedResourceId: ko.observable(null),
            linkedDisplayname: ko.observable(''),
            enrichExisting: ko.observable(true),
        }));
        self.items(items);
    };

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

    this.dismissSuggestions = (item) => {
        item.showSuggestions(false);
        item.suggestions([]);
    };

    this.useExisting = (item, suggestion) => {
        item.status('linked');
        item.linkedResourceId(suggestion.resourceId);
        item.linkedDisplayname(suggestion.displayname || '');
        item.resourceId(suggestion.resourceId);
        item.showSuggestions(false);
    };

    this.unlinkItem = (item) => {
        item.status('pending');
        item.linkedResourceId(null);
        item.linkedDisplayname('');
        item.resourceId(null);
        item.showSuggestions(true);
    };

    this.viewSuggestion = (suggestion) => {
        window.open(`/resource/${suggestion.resourceId}`, '_blank');
    };

    // =============================================
    // Dependencies
    // =============================================

    this.resolveDependencies = async () => {
        const deps = [];
        const seen = new Set();

        self.items().forEach((item) => {
            const location = item.locationLabel || item.location;
            if (location && location !== 'Origine inconnue' && !seen.has(`place:${location}`)) {
                seen.add(`place:${location}`);
                deps.push(self._makeDep(location, 'Place', PLACE_GRAPH_ID));
            }

            // Parent institution first (so collection can reference it)
            const parentInst = item.parentInstitutionLabel;
            const owner = item.collectionLabel;
            if (parentInst && parentInst !== owner && !seen.has(`group:${parentInst}`)) {
                seen.add(`group:${parentInst}`);
                deps.push(self._makeDep(parentInst, 'Group', GROUP_GRAPH_ID, null, location));
            }

            // Collection: member of parent institution, located at place
            if (owner && !seen.has(`group:${owner}`)) {
                seen.add(`group:${owner}`);
                const parentKey = (parentInst && parentInst !== owner) ? parentInst : null;
                deps.push(self._makeDep(owner, 'Group', GROUP_GRAPH_ID, parentKey, location));
            }

            const author = item.authorLabel;
            if (author && !seen.has(`person:${author}`)) {
                seen.add(`person:${author}`);
                deps.push(self._makeDep(author, 'Person', PERSON_GRAPH_ID));
            }
        });

        self.dependencies(deps);

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
                    const best = result.suggestions.find((s) => s.confidence === 'high');
                    if (best) {
                        dep.action('use_existing');
                        dep.existingId(best.resourceId);
                        dep.existingLabel(best.displayname || dep.key);
                        self._addAltName(dep);
                    } else {
                        dep.action('has_suggestions');
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

    this._makeDep = (label, type, graphId, parentKey, locationKey) => ({
        key: label,
        type: type,
        graphId: graphId,
        label: ko.observable(label),
        // search | has_suggestions | pending_confirm | use_existing | create | creating | created
        action: ko.observable('search'),
        existingId: ko.observable(null),
        existingLabel: ko.observable(''),
        suggestions: ko.observableArray([]),
        creating: ko.observable(false),
        // Relationships to other deps (for Groups)
        parentKey: parentKey || null,   // key of parent Group dep (member of)
        locationKey: locationKey || null, // key of Place dep (location)
    });

    // User picks a suggestion → direct link (intentional click)
    this.useExistingDep = (dep, suggestion) => {
        dep.action('use_existing');
        dep.existingId(suggestion.resourceId);
        dep.existingLabel(suggestion.displayname || dep.key);
        self._addAltName(dep);
    };

    // User confirms the Select2 selection (from pending_confirm → use_existing)
    this.confirmDepSelection = (dep) => {
        dep.action('use_existing');
        self._addAltName(dep);
    };

    // User cancels the Select2 preview (from pending_confirm → back)
    this.cancelDepSelection = (dep) => {
        dep.existingId(null);
        dep.existingLabel('');
        dep.action(dep.suggestions().length > 0 ? 'has_suggestions' : 'create');
    };

    this.dismissDepSuggestions = (dep) => {
        dep.suggestions([]);
        dep.action('create');
    };

    // Unlink from green state → back to search area
    this.unlinkDep = (dep) => {
        dep.existingId(null);
        dep.existingLabel('');
        dep.action(dep.suggestions().length > 0 ? 'has_suggestions' : 'create');
    };

    this.viewDepSuggestion = (suggestion) => {
        window.open(`/resource/${suggestion.resourceId}`, '_blank');
    };

    // Manually create a single dependency resource (resolves parent/location first)
    this.createDependency = async (dep) => {
        if (dep.action() === 'use_existing' || dep.action() === 'created' || dep.creating()) return;

        dep.creating(true);
        dep.action('creating');

        try {
            // Ensure parent Group exists first (for "member of")
            let memberOfId = null;
            if (dep.parentKey) {
                const parentDep = self.dependencies().find(
                    (d) => d.type === 'Group' && d.key === dep.parentKey
                );
                if (parentDep) {
                    if (!parentDep.existingId()) {
                        await self.createDependency(parentDep);
                    }
                    memberOfId = parentDep.existingId();
                }
            }

            // Ensure Place exists first (for "location")
            let locationId = null;
            if (dep.locationKey) {
                const placeDep = self.dependencies().find(
                    (d) => d.type === 'Place' && d.key === dep.locationKey
                );
                if (placeDep) {
                    if (!placeDep.existingId()) {
                        await self.createDependency(placeDep);
                    }
                    locationId = placeDep.existingId();
                }
            }

            const resp = await fetch('/api/biblissima/create-resource', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': self.getCSRFToken(),
                },
                body: JSON.stringify({
                    resourceType: dep.type,
                    biblissimaData: {
                        label: dep.key,
                        memberOf: memberOfId,
                        location: locationId,
                    },
                }),
            });

            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Creation failed');
            }

            const data = await resp.json();
            dep.existingId(data.resourceId);
            dep.existingLabel(data.displayname || dep.key);
            dep.action('created');

            const cacheKey = DEP_TYPE_MAP[dep.type]?.cacheKey;
            if (cacheKey) {
                self.dependencyCache[cacheKey][dep.key] = data.resourceId;
            }
        } catch (err) {
            console.error('Dependency creation failed:', dep.key, err);
            dep.action('create');
        } finally {
            dep.creating(false);
        }
    };

    // Add Biblissima label as alt name to existing resource (non-blocking)
    this._addAltName = async (dep) => {
        if (!dep.existingId() || !dep.key) return;
        try {
            await fetch('/api/biblissima/add-alt-name', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': self.getCSRFToken(),
                },
                body: JSON.stringify({
                    resourceId: dep.existingId(),
                    graphId: dep.graphId,
                    label: dep.key,
                }),
            });
        } catch (err) {
            console.warn('Alt name addition failed for:', dep.key, err);
        }
    };

    // =============================================
    // Resource creation
    // =============================================

    this.createResource = async (item) => {
        if (item.status() === 'created' || item.status() === 'skipped') return;

        item.status('creating');

        // Auto-create any unresolved deps before creating the item
        await self._ensureDepsCreated(item);

        const deps = {
            project: self.projectId,
            parentDocument: self.parentDocumentId,
        };

        // Place dep (fix: match on locationLabel || location)
        const locationKey = item.locationLabel || item.location;
        const placeDep = self.dependencies().find(
            (d) => d.type === 'Place' && d.key === locationKey
        );
        if (placeDep && placeDep.existingId()) {
            deps.currentLocation = placeDep.existingId();
        }

        // Owner Group deps (collection + parent institution, deduplicated)
        const ownerIds = new Set();
        const ownerDep = self.dependencies().find(
            (d) => d.type === 'Group' && d.key === item.collectionLabel
        );
        if (ownerDep && ownerDep.existingId()) {
            ownerIds.add(ownerDep.existingId());
        }
        const parentInstDep = self.dependencies().find(
            (d) => d.type === 'Group' && d.key === item.parentInstitutionLabel
                && d.key !== item.collectionLabel
        );
        if (parentInstDep && parentInstDep.existingId()) {
            ownerIds.add(parentInstDep.existingId());
        }
        if (ownerIds.size > 0) {
            deps.currentOwner = [...ownerIds];
        }

        // Person dep (author)
        const personDep = self.dependencies().find(
            (d) => d.type === 'Person' && d.key === item.authorLabel
        );
        if (personDep && personDep.existingId()) {
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

    // Auto-create deps that are not yet resolved for a given item
    this._ensureDepsCreated = async (item) => {
        const itemDeps = [];
        const locationKey = item.locationLabel || item.location;

        for (const dep of self.dependencies()) {
            if (dep.type === 'Place' && dep.key === locationKey) itemDeps.push(dep);
            if (dep.type === 'Group' && dep.key === item.collectionLabel) itemDeps.push(dep);
            if (dep.type === 'Group' && dep.key === item.parentInstitutionLabel && dep.key !== item.collectionLabel) itemDeps.push(dep);
            if (dep.type === 'Person' && dep.key === item.authorLabel) itemDeps.push(dep);
        }

        for (const dep of itemDeps) {
            if (!dep.existingId() && dep.action() !== 'creating') {
                await self.createDependency(dep);
            }
        }
    };

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

    this.skipItem = (item) => {
        item.status('skipped');
    };

    this.editResource = (item) => {
        if (item.resourceId()) {
            window.open(`/resource/${item.resourceId()}`, '_blank');
        }
    };

    this.viewDuplicate = (item) => {
        if (item.duplicateResourceId()) {
            window.open(`/resource/${item.duplicateResourceId()}`, '_blank');
        }
    };

    this.forceCreate = (item) => {
        item.status('pending');
        item.duplicateResourceId(null);
        self.createResource(item);
    };

    this.refreshItem = async (item) => {
        if (!item.resourceId()) return;
        try {
            const resp = await fetch(
                `${arches.urls.api_resources(item.resourceId())}?format=json&compact=false&v=beta`
            );
            if (resp.ok) {
                const data = await resp.json();
                if (data.displayname) {
                    item.label = data.displayname;
                    self.items.valueHasMutated();
                }
            }
        } catch (err) {
            console.warn('Failed to refresh item:', err);
        }
    };

    this._focusHandler = () => {
        self.items().forEach((item) => {
            if (item.status() === 'created' && item.resourceId()) {
                self.refreshItem(item);
            }
        });
    };
    window.addEventListener('focus', this._focusHandler);

    this.dispose = () => {
        window.removeEventListener('focus', self._focusHandler);
    };

    // =============================================
    // Dep picker (Select2) — selection goes to pending_confirm
    // =============================================

    this.buildDepPickerConfig = (dep) => {
        const selectedValue = ko.observable(null);
        selectedValue.subscribe((val) => {
            if (val && typeof val === 'string' && val.length > 10) {
                fetch(`${arches.urls.api_resources(val)}?format=json&compact=false&v=beta`)
                    .then((r) => r.ok ? r.json() : null)
                    .then((data) => {
                        dep.existingId(val);
                        dep.existingLabel(data?.displayname || dep.key);
                        dep.action('pending_confirm');
                    })
                    .catch(() => {
                        dep.existingId(val);
                        dep.existingLabel(dep.key);
                        dep.action('pending_confirm');
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
            minimumInputLength: 0,
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
                    const term = (requestParams.term || '').trim();
                    if (term) {
                        params['term-filter'] = JSON.stringify([{
                            inverted: false,
                            type: 'string',
                            context: '',
                            context_label: '',
                            id: term,
                            text: term,
                            value: term,
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

    // =============================================
    // Submit
    // =============================================

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

    // =============================================
    // Helpers
    // =============================================

    this.getCSRFToken = () => {
        const cookie = document.cookie.split(';').find((c) => c.trim().startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : '';
    };

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

    // =============================================
    // Init
    // =============================================

    this.initializeItems();
    this.resolveDependencies();
    this.checkDuplicates();
};

ko.components.register('biblissima-create-step', {
    viewModel: viewModel,
    template: biblissimaCreateStepTemplate,
});

export default viewModel;
