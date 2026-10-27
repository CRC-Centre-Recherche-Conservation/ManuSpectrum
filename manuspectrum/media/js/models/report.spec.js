/**
 * Vitest unit spec — models/report.js (project wrapper over the core report model).
 *
 * The core model is mocked by a stand-in with the members the wrapper uses:
 * `initialize` builds `relatedResourcesLookup` from `related_resources`
 * through `updateRelatedResourcesLookup`, which adds a graph's entry once
 * (its total from the summary or from the paginated answer, as the core
 * does) and appends the rows it is given; `getRelatedResources` asks the next
 * page of a graph, or all of it. `$.ajax` answers from the routes the report
 * reads: `related_resources/<id>?page=n[&resourceinstance_graphid=]`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import $ from 'jquery';

vi.mock('arches', () => ({
    default: {
        relatedResourcesExportLimit: 500,
        relatedResourcesPerPage: 15,
        urls: { related_resources: '/en/related_resources/' },
    },
}));

vi.mock('arches/arches/app/media/js/models/report', async () => {
    const ko = (await import('knockout')).default;
    const jquery = (await import('jquery')).default;
    function CoreReportModel(options) {
        this.attributes = options;
        this.initialize(options);
    }
    CoreReportModel.prototype.initialize = function(options) {
        this.relatedResourcesLookup = ko.observable({});
        if (options.related_resources) {
            this.updateRelatedResourcesLookup(options.related_resources);
        }
    };
    CoreReportModel.prototype.updateRelatedResourcesLookup = vi.fn(function(json) {
        const lookup = this.relatedResourcesLookup();
        for (const [graphId, value] of Object.entries(json)) {
            if (!lookup[graphId]) {
                lookup[graphId] = {
                    graphId,
                    loadedRelatedResources: ko.observableArray(),
                    paginator: ko.observable(),
                    totalRelatedResources: value.related_resources
                        ? value.related_resources.total.value
                        : value.resources.length,
                };
            }
            const entry = lookup[graphId];
            entry.paginator(value.paginator);
            const rows = value.resources || value.related_resources.related_resources;
            rows.forEach((row) => entry.loadedRelatedResources.push(row.resourceinstanceid));
        }
        this.relatedResourcesLookup(lookup);
    });
    CoreReportModel.prototype.getRelatedResources = vi.fn(function(loadAll, resource) {
        const data = loadAll
            ? { paginate: false, resourceinstance_graphid: resource.graphId }
            : { page: resource.paginator().next_page_number, resourceinstance_graphid: resource.graphId };
        return jquery.ajax({ url: '/en/related_resources/', data }).done((json) => {
            this.updateRelatedResourcesLookup({ [resource.graphId]: json });
        });
    });
    CoreReportModel.extend = function(protoProps) {
        const Parent = this;
        function Child(options) {
            Parent.call(this, options);
        }
        Child.prototype = Object.assign(Object.create(Parent.prototype), protoProps);
        return Child;
    };
    return { default: CoreReportModel };
});

import CoreReportModel from 'arches/arches/app/media/js/models/report';
import ReportModel from './report.js';

const PERSON = 'person-1';
const ANALYSIS = 'graph-analysis';
const SAMPLE = 'graph-sample';

function summaryOf(counts) {
    return Object.entries(counts).map(([graphid, n]) => ({
        graphid,
        name: graphid,
        resources: Array.from({ length: n }, (_, i) => ({
            resourceinstanceid: `${graphid}-${i}`,
            displayname: `${graphid} ${i}`,
            relationships: ['observed'],
        })),
    }));
}

function page(graphid, total, number = 1) {
    const start = 15 * (number - 1);
    const ids = Array.from({ length: Math.max(0, Math.min(15, total - start)) }, (_, i) => `${graphid}-${start + i}`);
    return {
        related_resources: {
            total: { value: total },
            resource_relationships: ids.map((id) => ({ to_resource: PERSON, from_resource: id })),
            related_resources: ids.map((id) => ({ resourceinstanceid: id })),
        },
        paginator: { has_next: start + 15 < total, next_page_number: number + 1 },
    };
}

let totals;
let asked;
let failing;

beforeEach(() => {
    asked = [];
    failing = () => false;
    CoreReportModel.prototype.updateRelatedResourcesLookup.mockClear();
    CoreReportModel.prototype.getRelatedResources.mockClear();
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    vi.spyOn($, 'ajax').mockImplementation((options) => {
        asked.push(options);
        if (failing(options.data)) {
            return $.Deferred().reject().promise();
        }
        const graph = options.data.resourceinstance_graphid;
        const total = graph ? totals[graph] : Object.values(totals).reduce((a, b) => a + b, 0);
        return $.Deferred().resolve(page(graph || 'all', total, options.data.page)).promise();
    });
});

afterEach(() => {
    vi.restoreAllMocks();
});

function report(summary) {
    return new ReportModel({ graph: {}, resourceid: PERSON, related_resources: summary });
}

describe('the related resources of a report', () => {
    it('hands the core the report API summary keyed by graph id', async () => {
        totals = { [ANALYSIS]: 2, [SAMPLE]: 1 };
        const summary = summaryOf(totals);
        const model = report(summary);
        await model.relatedResourcesPaged;

        expect(CoreReportModel.prototype.updateRelatedResourcesLookup).toHaveBeenCalledWith({
            [ANALYSIS]: summary[0],
            [SAMPLE]: summary[1],
        });
        expect(Object.keys(model.relatedResourcesLookup())).toEqual([ANALYSIS, SAMPLE]);
    });

    it('keeps a summary below the cap: one count, no page per graph', async () => {
        totals = { [ANALYSIS]: 2, [SAMPLE]: 1 };
        const model = report(summaryOf(totals));
        await model.relatedResourcesPaged;

        expect(asked.map((options) => [options.url, options.data])).toEqual([
            [`/en/related_resources/${PERSON}`, { page: 1 }],
        ]);
        expect(model.relatedResourcesLookup()[ANALYSIS].loadedRelatedResources()).toHaveLength(2);
    });

    it('keeps a summary that holds fewer relations than the count when the count is below the cap', async () => {
        totals = { [ANALYSIS]: 300 };
        const model = report(summaryOf({ [ANALYSIS]: 120 }));
        await model.relatedResourcesPaged;

        expect(asked).toHaveLength(1);
        expect(model.relatedResourcesLookup()[ANALYSIS].loadedRelatedResources()).toHaveLength(120);
    });

    it('pages every graph, the empty ones included, when the count reaches the cap', async () => {
        totals = { [ANALYSIS]: 1470, [SAMPLE]: 31 };
        const model = report(summaryOf({ [ANALYSIS]: 500, [SAMPLE]: 0 }));
        const summarised = model.relatedResourcesLookup()[SAMPLE];
        await model.relatedResourcesPaged;

        expect(asked.map((options) => options.data)).toEqual([
            { page: 1 },
            { page: 1, resourceinstance_graphid: ANALYSIS },
            { page: 1, resourceinstance_graphid: SAMPLE },
        ]);
        const lookup = model.relatedResourcesLookup();
        expect(Object.keys(lookup)).toEqual([ANALYSIS, SAMPLE]);
        expect(lookup[SAMPLE]).not.toBe(summarised);
        expect(lookup[ANALYSIS].totalRelatedResources).toBe(1470);
        expect(lookup[ANALYSIS].loadedRelatedResources()).toHaveLength(15);
        expect(lookup[ANALYSIS].paginator().has_next).toBe(true);
        expect(lookup[SAMPLE].totalRelatedResources).toBe(31);
    });

    it('keeps the summary, untouched, when a page fails, and says so in the console', async () => {
        totals = { [ANALYSIS]: 1470, [SAMPLE]: 31 };
        failing = (data) => data.resourceinstance_graphid === SAMPLE;
        const model = report(summaryOf({ [ANALYSIS]: 500, [SAMPLE]: 0 }));
        const before = model.relatedResourcesLookup();
        const analyses = before[ANALYSIS];
        await model.relatedResourcesPaged;

        expect(model.relatedResourcesLookup()).toBe(before);
        expect(model.relatedResourcesLookup()[ANALYSIS]).toBe(analyses);
        expect(analyses.loadedRelatedResources()).toHaveLength(500);
        expect(console.warn).toHaveBeenCalled();
    });

    it('loads the next pages up to the cap on « Load all » past the cap, keeping the paging', async () => {
        totals = { [ANALYSIS]: 1470 };
        const model = report(summaryOf({ [ANALYSIS]: 500 }));
        await model.relatedResourcesPaged;
        const entry = model.relatedResourcesLookup()[ANALYSIS];

        await model.getRelatedResources(true, entry);

        expect(asked.filter((options) => options.data.paginate === false)).toEqual([]);
        expect(entry.loadedRelatedResources()).toHaveLength(15 + 15 * Math.ceil(500 / 15));
        expect(entry.paginator().has_next).toBe(true);
    });

    it('runs one « Load all » chain per graph however many times it is clicked', async () => {
        totals = { [ANALYSIS]: 1470 };
        const model = report(summaryOf({ [ANALYSIS]: 500 }));
        await model.relatedResourcesPaged;
        const entry = model.relatedResourcesLookup()[ANALYSIS];

        const first = model.getRelatedResources(true, entry);
        const again = model.getRelatedResources(true, entry);
        const more = model.getRelatedResources(false, entry);
        await Promise.all([first, again, more]);

        expect(again).toBe(first);
        expect(more).toBe(first);
        expect(entry.loadedRelatedResources()).toHaveLength(15 + 15 * Math.ceil(500 / 15));
    });

    it('stops a « Load all » chain on a failed page and keeps the paging', async () => {
        totals = { [ANALYSIS]: 1470 };
        const model = report(summaryOf({ [ANALYSIS]: 500 }));
        await model.relatedResourcesPaged;
        const entry = model.relatedResourcesLookup()[ANALYSIS];
        failing = (data) => data.page === 4;

        await model.getRelatedResources(true, entry);

        expect(entry.loadedRelatedResources()).toHaveLength(45);
        expect(entry.paginator().has_next).toBe(true);
        expect(console.warn).toHaveBeenCalled();
        failing = () => false;
        await model.getRelatedResources(false, entry);
        expect(entry.loadedRelatedResources()).toHaveLength(60);
    });

    it('lets the core load all of a graph within the cap', async () => {
        totals = { [ANALYSIS]: 40 };
        const model = report(summaryOf({ [ANALYSIS]: 40 }));
        await model.relatedResourcesPaged;

        model.getRelatedResources(true, model.relatedResourcesLookup()[ANALYSIS]);

        expect(CoreReportModel.prototype.getRelatedResources).toHaveBeenCalledWith(
            true,
            model.relatedResourcesLookup()[ANALYSIS],
        );
    });

    it('asks nothing for a report model built without the API summary', () => {
        new ReportModel({ graph: {}, resourceid: PERSON });
        new ReportModel({ graph: {}, related_resources: { [ANALYSIS]: page(ANALYSIS, 3) } });

        expect(asked).toEqual([]);
    });
});
