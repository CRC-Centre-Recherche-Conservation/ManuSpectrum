// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science

import _ from 'underscore';
import ko from 'knockout';
import uuid from 'uuid';
import arches from 'arches';
import addThingsStepTemplate from 'templates/views/components/workflows/create-project-workflow/add-things-step.htm';
import 'bindings/select2-query';
import 'views/components/resource-instance-creator';
import 'views/components/search/paging-filter';

const DOCUMENT_GRAPH_ID = '0c8226c1-11a9-4c48-9601-a7a0c6f2df6b';
const STUDIED_OBJECTS_NODEGROUP_ID = 'a8fb3c9e-bbc4-11ef-bd5f-ed806b645d76';
const STUDIED_OBJECTS_NODE_ID = 'a8fb3c9e-bbc4-11ef-bd5f-ed806b645d76';

const getQueryObject = () => {
    const query = _.chain(decodeURIComponent(location.search).slice(1).split('&'))
        .map((item) => {
            if (item) return item.split('=');
        })
        .compact()
        .object()
        .value();
    return query;
};

const viewModel = function(params) {
    const self = this;

    self.newResourceInstance = ko.observable();
    self.documentGraphId = params.documentGraphId || DOCUMENT_GRAPH_ID;

    _.extend(this, params.form);

    this.newResourceInstance.subscribe(async (data) => {
        if (!data) { return; }
        await self.updateSearchResults({
            type: "string",
            context: "",
            context_label: "Search Term",
            id: data,
            text: data,
            value: data,
            selected: true,
            inverted: false
        });
        if (this.targetResources()?.[0]) {
            this.updateTileData(this.targetResources()[0]);
        }
        self.updateSearchResults(self.termFilter());
    });

    this.projectResourceId = ko.observable();
    this.studiedObjectsTileId = ko.observable();
    this.reportDataLoading = ko.observable(ko.unwrap(params.loading));

    if (params.projectStepData) {
        const projectStepData = params.projectStepData;
        this.projectResourceId(projectStepData.projectResourceId);
    } else if (params.resourceid) {
        this.projectResourceId(params.resourceid);
    }

    this.selectedTab = ko.observable();
    this.searchResults = { timestamp: ko.observable() };
    this.targetResource = ko.observable();
    this.toggleRelationshipCandidacy = ko.observable();
    this.isResourceRelatable = ko.observable();
    this.filters = {
        'paging-filter': ko.observable(),
        'search-results': ko.observable(),
    };
    this.searchFilterVms = {
        'paging-filter': ko.observable()
    };
    this.termFilter = ko.observable();
    this.totalResults = ko.observable();
    this.query = ko.observable(getQueryObject());
    this.selectedTerm = ko.observable();
    this.targetResources = ko.observableArray([]);
    this.targetResourceSearchValue = ko.observable();
    this.termOptions = [];
    this.value = ko.observableArray([]).extend({ rateLimit: 100 });
    this.startValue = ko.observableArray();
    this.selectedResources = ko.observableArray([]);
    this.addedValues = ko.observableArray();
    this.removedValues = ko.observableArray();

    this.dirty = ko.pureComputed(() => {
        if (self.startValue() && self.value()) {
            return !!(self.startValue().find(x => !self.value().includes(x))
                || self.value().find(x => !self.startValue().includes(x)));
        }
        return false;
    });

    // keep the form dirty while no studied-objects tile exists so the
    // workflow always goes through submit() (and its empty-selection
    // guard) instead of silently completing this required step
    this.mustSave = ko.pureComputed(() => {
        return self.dirty() || (!self.studiedObjectsTileId() && self.value().length === 0);
    });
    this.mustSave.subscribe((mustSave) => {
        if (ko.isObservable(params.form.dirty)) {
            params.form.dirty(mustSave);
        }
    });
    if (ko.isObservable(params.form.dirty)) {
        params.form.dirty(this.mustSave());
    }

    this.value.subscribe((a) => {
        a.forEach((action) => {
            const id = ko.unwrap(action.value).resourceinstanceid;
            if (action.status === 'added') {
                const resource = self.value().find(r => r.resourceinstanceid === id);
                if (resource) { self.selectedResources.push(resource); }
            } else if (action.status === 'deleted') {
                const toRemove = self.selectedResources().find(r => r.resourceinstanceid === id);
                if (toRemove) { self.selectedResources.remove(toRemove); }
            }
        });
        self.sortSelectedResources();
    }, null, "arrayChange");

    const loadExistingStudiedObjects = async () => {
        const projectRelatedResources = await (await window.fetch(`${arches.urls.related_resources}${self.projectResourceId()}`)).json();
        const existingDocuments = projectRelatedResources.related_resources.related_resources.filter(
            x => x.graph_id === self.documentGraphId
        );

        if (existingDocuments.length > 0) {
            self.startValue(existingDocuments);
            existingDocuments.forEach((val) => {
                self.value.push(val);
            });
        }
    };

    this.sortSelectedResources = () => {
        self.selectedResources.sort((a, b) => {
            const aName = self.getStringValue(a.displayname).toLowerCase();
            const bName = self.getStringValue(b.displayname).toLowerCase();
            return aName.localeCompare(bName);
        });
    };

    this.initialize = () => {
        if (params.value()) {
            const cachedValue = ko.unwrap(params.value);
            if (cachedValue.studiedObjectsTileId) {
                self.studiedObjectsTileId(cachedValue.studiedObjectsTileId);
            }
            if (cachedValue.value) {
                self.startValue(ko.unwrap(cachedValue.value));
                self.startValue().forEach((val) => {
                    self.value.push(val);
                });
            }
        } else if (params.action === "update") {
            loadExistingStudiedObjects();
            params.form.lockExternalStep("select-project", true);
        }

        // the workflow marks a step complete whenever cached data exists;
        // an empty cart must never count as complete (documents required)
        if (!self.value().length) {
            self.complete(false);
        }
    };

    this.resetTile = () => {
        if (self.startValue()) {
            self.value.removeAll();
            self.startValue().forEach((val) => {
                self.value.push(val);
            });
        }
    };
    params.form.reset = this.resetTile;

    this.updateTileData = (resource) => {
        const val = self.value().find((item) => {
            return ko.unwrap(item).resourceinstanceid === resource.resourceinstanceid;
        });

        if (val) {
            self.value.remove(val);
        } else {
            self.value.push(resource);
        }
    };

    const buildResourceInstanceList = (resources) => {
        return resources.map((resource) => ({
            resourceId: resource.resourceinstanceid,
            ontologyProperty: "",
            inverseOntologyProperty: ""
        }));
    };

    const reportSaveError = (message) => {
        params.pageVm.alert(
            new params.form.AlertViewModel(
                'ep-alert-red',
                arches.translations.issueSavingWorkflowStep,
                message
            )
        );
        if (ko.isObservable(params.form.error)) {
            // reset first so setting the same message twice still notifies
            params.form.error(null);
            params.form.error(message);
        }
    };

    this.saveState = ko.observable('idle'); // idle | saving | saved | error
    this.saveErrorMessage = ko.observable('');

    let debounceTimer = null;
    let savedFadeTimer = null;
    let saveQueue = Promise.resolve();

    const isInSync = () => {
        const saved = (self.startValue() || []).map((r) => r.resourceinstanceid);
        const current = self.value().map((r) => r.resourceinstanceid);
        return current.length === saved.length && current.every((id) => saved.includes(id));
    };

    const postTile = (resources) => {
        const tile = {
            tileid: self.studiedObjectsTileId() || "",
            nodegroup_id: STUDIED_OBJECTS_NODEGROUP_ID,
            parenttile_id: null,
            resourceinstance_id: self.projectResourceId(),
            sortorder: 0,
            tiles: {},
            data: {
                [STUDIED_OBJECTS_NODE_ID]: buildResourceInstanceList(resources)
            },
            transaction_id: params.form.workflowId
        };

        return window.fetch(arches.urls.api_tiles(self.studiedObjectsTileId() || uuid.generate()), {
            method: 'POST',
            credentials: 'include',
            body: JSON.stringify(tile),
            headers: {
                'Content-Type': 'application/json'
            },
        }).then((response) => {
            if (response.ok) {
                return response.json();
            }
            return response.json().then(
                (error) => Promise.reject(new Error(error?.message || arches.translations.issueSavingWorkflowStep)),
                () => Promise.reject(new Error(arches.translations.issueSavingWorkflowStep))
            );
        });
    };

    // saves are serialized: each call appends one sync attempt to the queue,
    // reads the cart at run time and no-ops when already in sync, so the
    // trailing state always wins. Resolves true when the cart is persisted
    // (or legitimately empty), false on save failure.
    const persist = () => {
        const run = saveQueue.then(async () => {
            if (self.value().length === 0) {
                // an empty cart cannot be saved (required node): keep it a
                // local state — Next stays blocked through complete(false) —
                // and keep the tileid so a later save reuses the same tile
                self.startValue([]);
                self.savedData({
                    value: [],
                    projectResourceId: ko.unwrap(self.projectResourceId),
                    studiedObjectsTileId: ko.unwrap(self.studiedObjectsTileId),
                });
                self.complete(false);
                self.saveState('idle');
                return true;
            }

            if (isInSync()) {
                if (self.saveState() === 'saving') {
                    self.saveState('idle');
                }
                self.complete(true);
                return true;
            }

            self.saveState('saving');
            const snapshot = self.value().slice();
            try {
                const data = await postTile(snapshot);
                self.studiedObjectsTileId(data.tileid);
                self.startValue(snapshot);
                self.savedData({
                    value: snapshot,
                    projectResourceId: ko.unwrap(self.projectResourceId),
                    studiedObjectsTileId: data.tileid,
                });
                self.saveErrorMessage('');
                params.pageVm.alert("");
                if (isInSync()) {
                    self.complete(true);
                    self.saveState('saved');
                    clearTimeout(savedFadeTimer);
                    savedFadeTimer = setTimeout(() => {
                        if (self.saveState() === 'saved') {
                            self.saveState('idle');
                        }
                    }, 2500);
                }
                return true;
            } catch (err) {
                console.error(err);
                self.saveErrorMessage(err.message);
                self.saveState('error');
                self.complete(false);
                return false;
            }
        });
        saveQueue = run.then(() => {}, () => {});
        return run;
    };

    // auto-save: any cart change gives immediate feedback and persists once
    // the user pauses (debounced), so Back/Next can never lose a selection
    this.value.subscribe(() => {
        if (isInSync()) { return; }
        self.saveState('saving');
        self.complete(false);
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(persist, 500);
    });

    this.retrySave = () => {
        persist();
    };

    this.removeAll = () => {
        self.value.removeAll();
    };

    // footer Next: flush any pending change before advancing; an empty
    // cart is rejected with the existing alert
    params.form.save = () => {
        if (self.value().length === 0) {
            reportSaveError(arches.translations.addThingsNoDocuments);
            return;
        }
        self.saving(true);
        clearTimeout(debounceTimer);
        persist().then((success) => {
            self.saving(false);
            if (!success) {
                reportSaveError(self.saveErrorMessage() || arches.translations.issueSavingWorkflowStep);
            }
        });
    };
    params.form.onSaveSuccess = () => {};

    this.targetResourceSelectConfig = {
        value: self.selectedTerm,
        minimumInputLength: 2,
        placeholder: arches.translations.documentPlaceholder || 'Search for a document...',
        clickBubble: true,
        multiple: false,
        closeOnSelect: true,
        allowClear: true,
        ajax: {
            url: arches.urls.search_terms,
            dataType: 'json',
            quietMillis: 250,
            data: (requestParams) => {
                const term = requestParams.term || '';
                return { q: term };
            },
            processResults: (data, params) => {
                const results = data.terms;
                results.unshift({
                    type: 'string',
                    context: '',
                    context_label: 'Search Term',
                    id: params.term,
                    text: params.term,
                    value: params.term
                });
                self.termOptions = results;

                const filteredResults = results.filter((result) => (
                    result.context_label.includes("Document") ||
                    result.context_label.includes("Search Term")
                ));
                return { results: filteredResults };
            }
        },
        templateResult: (item) => {
            if (item.context_label === 'Search Term') {
                return `<strong><u>${item.text}</u></strong>`;
            }
            return item.text;
        },
        templateSelection: (item) => item.text,
        escapeMarkup: (m) => m
    };

    const getResultData = async (termFilter, pagingFilter) => {
        const filters = {};
        _.each(self.filters, (_value, key) => {
            if (key !== 'paging-filter' && key !== 'search-results') {
                delete self.filters[key];
            }
        });

        if (termFilter) {
            termFilter.inverted = false;
            filters["term-filter"] = JSON.stringify([termFilter]);
        }

        filters["resource-type-filter"] = JSON.stringify([{
            graphid: self.documentGraphId,
            inverted: false
        }]);

        if (pagingFilter) {
            filters['paging-filter'] = pagingFilter;
            self.filters['paging-filter'](pagingFilter);
        } else {
            filters['paging-filter'] = 1;
        }

        self.reportDataLoading(true);

        const setUpReports = async () => {
            const filterParams = Object.entries(filters).map(([key, val]) => `${key}=${val}`).join('&');
            await fetch(arches.urls.search_results + '?' + filterParams)
                .then(response => response.json())
                .then(data => {
                    _.each(self.searchResults, (_value, key) => {
                        if (key !== 'timestamp') {
                            delete self.searchResults[key];
                        }
                    });
                    _.each(data, (value, key) => {
                        if (key !== 'timestamp') {
                            self.searchResults[key] = value;
                        }
                    });
                    self.searchResults.timestamp(data.timestamp);

                    self.totalResults(data.total_results);
                    const resources = data.results.hits.hits.map(source => source._source);
                    self.targetResources(resources);
                    self.reportDataLoading(false);
                });
        };
        await setUpReports();
    };

    this.updateSearchResults = async (termFilter, pagingFilter) => {
        await getResultData(termFilter, pagingFilter);
    };

    this.selectedTerm.subscribe((val) => {
        self.termFilter(self.termOptions.find(x => val == x.id));
        self.updateSearchResults(self.termFilter());
    });

    this.query.subscribe((query) => {
        self.updateSearchResults(self.termFilter(), query['paging-filter']);
    });

    this.initialize();

    // Load initial search results (all documents)
    this.updateSearchResults();

    this.stripTags = (original) => original?.replace(/(<([^>]+)>)/gi, "");

    this.getStringValue = (value) => {
        if (typeof value === 'string') {
            return value;
        }
        if (Array.isArray(value)) {
            return value.find(str => str.language == arches.activeLanguage)?.value || value[0]?.value || '';
        }
        return '';
    };
};

ko.components.register('add-things-step', {
    viewModel: viewModel,
    template: addThingsStepTemplate
});

export default viewModel;
