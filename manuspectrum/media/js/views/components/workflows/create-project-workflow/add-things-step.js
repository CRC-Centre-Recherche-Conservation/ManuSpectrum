// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science

import $ from 'jquery';
import _ from 'underscore';
import ko from 'knockout';
import koMapping from 'knockout-mapping';
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

    const limit = 7;
    this.projectResourceId = ko.observable();
    this.studiedObjectsTileId = ko.observable();
    this.reportDataLoading = ko.observable(ko.unwrap(params.loading));
    let projectName;

    if (params.projectStepData) {
        const projectStepData = params.projectStepData;
        projectName = projectStepData.name?.value;
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

    this.dirty.subscribe((dirty) => {
        if (ko.isObservable(params.form.dirty)) {
            params.form.dirty(dirty);
        }
    });

    this.value.subscribe((a) => {
        a.forEach((action) => {
            if (action.status === 'added') {
                const resource = self.value().find(
                    r => r.resourceinstanceid === ko.unwrap(action.value).resourceinstanceid
                );
                self.selectedResources.push(resource);
            } else if (action.status === 'deleted') {
                self.selectedResources().forEach((val) => {
                    if (val.resourceinstanceid === ko.unwrap(action.value).resourceinstanceid) {
                        self.selectedResources.remove(val);
                    }
                });
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
        const sortedDisplayNames = self.selectedResources().map(
            res => self.getStringValue(res.displayname)
        ).map(val => val.toLowerCase()).sort();

        const resourceSortFn = (a, b) => {
            const aIndex = sortedDisplayNames.indexOf(self.getStringValue(a.displayname).toLowerCase());
            const bIndex = sortedDisplayNames.indexOf(self.getStringValue(b.displayname).toLowerCase());
            if (aIndex < bIndex) return -1;
            if (aIndex === bIndex) return 0;
            return 1;
        };
        this.selectedResources().sort(resourceSortFn);
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

    const buildResourceInstanceList = () => {
        return self.value().map((resource) => ({
            resourceId: resource.resourceinstanceid,
            ontologyProperty: "",
            inverseOntologyProperty: ""
        }));
    };

    this.submit = () => {
        self.complete(false);
        self.saving(true);

        const tileData = {
            [STUDIED_OBJECTS_NODE_ID]: buildResourceInstanceList()
        };

        const tile = {
            tileid: self.studiedObjectsTileId() || "",
            nodegroup_id: STUDIED_OBJECTS_NODEGROUP_ID,
            parenttile_id: null,
            resourceinstance_id: self.projectResourceId(),
            sortorder: 0,
            tiles: {},
            data: tileData,
            transaction_id: params.form.workflowId
        };

        window.fetch(arches.urls.api_tiles(self.studiedObjectsTileId() || uuid.generate()), {
            method: 'POST',
            credentials: 'include',
            body: JSON.stringify(tile),
            headers: {
                'Content-Type': 'application/json'
            },
        }).then((response) => {
            if (response.ok) {
                return response.json();
            } else {
                throw new Error('Failed to save tile');
            }
        }).then((data) => {
            self.studiedObjectsTileId(data.tileid);
            self.savedData({
                value: ko.unwrap(self.value),
                projectResourceId: ko.unwrap(self.projectResourceId),
                studiedObjectsTileId: ko.unwrap(self.studiedObjectsTileId),
            });
            self.saving(false);
            self.complete(true);
        }).catch((err) => {
            console.error(err);
            const startValue = ko.unwrap(self.startValue);
            self.value(startValue);
            self.saving(false);
        });
    };

    params.form.save = self.submit;
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
