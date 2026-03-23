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
    this.totalCount = ko.computed(() => self.items().length);
    this.allDone = ko.computed(() =>
        self.totalCount() > 0 && self.items().every(
            (i) => i.status() === 'created' || i.status() === 'skipped'
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
            status: ko.observable('pending'),   // pending | creating | created | error | skipped | duplicate
            resourceId: ko.observable(null),
            errorMessage: ko.observable(''),
            duplicateResourceId: ko.observable(null),
        }));
        self.items(items);
    };

    // Check for duplicates
    this.checkDuplicates = async () => {
        const identifiers = self.items()
            .map((i) => i.arkId)
            .filter(Boolean);

        if (identifiers.length === 0) {
            self.loading(false);
            return;
        }

        const graphId = self.resourceType === 'Document'
            ? '0c8226c1-11a9-4c48-9601-a7a0c6f2df6b'
            : 'd47595b4-f8a6-419c-8f33-b388206280c4';

        try {
            const resp = await fetch(
                `/api/biblissima/check-duplicates?identifiers=${identifiers.join(',')}&graphId=${graphId}`
            );
            const data = await resp.json();
            const results = data.results || {};

            self.items().forEach((item) => {
                if (item.arkId && results[item.arkId]) {
                    item.status('duplicate');
                    item.duplicateResourceId(results[item.arkId]);
                }
            });
        } catch (err) {
            console.error('Duplicate check failed:', err);
        }
        self.loading(false);
    };

    // Resolve dependencies (extract unique places, persons, groups from data)
    this.resolveDependencies = () => {
        const deps = [];
        const seen = new Set();

        self.items().forEach((item) => {
            // Place from location
            const location = item.location;
            if (location && location !== 'Origine inconnue' && !seen.has(`place:${location}`)) {
                seen.add(`place:${location}`);
                deps.push({
                    key: location,
                    type: 'Place',
                    label: ko.observable(location),
                    action: ko.observable('create'),
                    existingId: ko.observable(null),
                    existingLabel: ko.observable(''),
                });
            }

            // Author
            const author = item.authorLabel;
            if (author && !seen.has(`person:${author}`)) {
                seen.add(`person:${author}`);
                deps.push({
                    key: author,
                    type: 'Person',
                    label: ko.observable(author),
                    action: ko.observable('create'),
                    existingId: ko.observable(null),
                    existingLabel: ko.observable(''),
                });
            }
        });

        self.dependencies(deps);
        self.dependenciesResolved(true);
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
        params.value({
            createdResources: created.map((i) => ({
                resourceId: i.resourceId(),
                label: i.label || i.legend || '',
                arkId: i.arkId,
                manuscript: i.manuscript,
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
