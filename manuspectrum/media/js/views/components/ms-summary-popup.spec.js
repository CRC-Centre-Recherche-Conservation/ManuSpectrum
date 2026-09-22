/**
 * Vitest unit spec — ms-summary-popup.js.
 *
 * The component is the only reader of the summary endpoint, and it renders a
 * payload the server builds from user data. Two invariants carry the weight:
 * every URL it puts in the DOM is built here from `arches.urls`, never taken
 * from the payload, and the template binds with `text:` only. The rest covers
 * the states a popup goes through (loading, the four refusals, the degraded
 * and the unconfigured payloads) and the disposal that releases the page cache.
 *
 * Note: this file lives under media/js/views/components/, which coverage.include
 * does not target, so it executes without touching the coverage gate.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

vi.mock('arches', () => ({
    default: {
        urls: { resource_report: '/fr/report/' },
        translations: {
            summaryError: 'The summary could not be loaded.',
            summaryForbidden: 'You do not have permission to view this resource.',
            summaryNotFound: 'This resource no longer exists.',
            summaryUnavailable: 'Details are unavailable right now.',
            summaryEmpty: 'No details to show.',
            summaryMore: '+{n}',
            summarySpectrum: 'Spectrum',
        },
    },
}));

// The core helper lives outside the project root, where vite cannot resolve
// its `knockout` import. Stand in for the branch this viewmodel takes: with no
// `disposables` list, every property of the object that can be disposed is.
vi.mock('utils/dispose', () => ({
    default: (obj) =>
        Object.keys(obj).forEach((key) => {
            const value = obj[key];
            if (value && typeof value.dispose === 'function') value.dispose();
        }),
}));

vi.mock('utils/summary-popup', () => ({
    acquireSummary: vi.fn(),
    invalidateSummary: vi.fn(),
}));

import { acquireSummary, invalidateSummary } from 'utils/summary-popup';

/**
 * The component template, read from disk.
 *
 * Vitest stubs `templates/*.htm` imports, so this is the only place the real
 * markup is exercised. Django tags render as inert text in jsdom, which leaves
 * the Knockout bindings intact.
 */
const template = fs.readFileSync(
    path.join(
        path.dirname(fileURLToPath(import.meta.url)),
        '..',
        '..',
        '..',
        '..',
        'templates',
        'views',
        'components',
        'ms-summary-popup.htm'
    ),
    'utf-8'
);

const ID = '11111111-1111-4111-8111-111111111111';
const PLACE_ID = '583519ee-0000-4000-8000-000000000001';

/** Every acquisition the component made, newest last. */
let handles;

const newHandle = () => {
    let settle;
    const promise = new Promise((resolve) => {
        settle = resolve;
    });
    const handle = { promise, release: vi.fn(), settle };
    handles.push(handle);
    return handle;
};

/** Let the `.then()` chains behind a settled acquisition run. */
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const payload = (overrides = {}) => ({
    id: ID,
    configured: true,
    graph: { slug: 'document', name: 'Document' },
    name: 'Avranches. BM, Ms. 59',
    fields: [
        {
            key: 'period_production',
            label: 'Période',
            style: 'chip',
            values: ['Moyen Âge classique'],
            more: 0,
        },
        {
            key: 'production_at_place',
            label: 'Lieu',
            style: 'link',
            values: [{ id: PLACE_ID, label: 'Le Mont-Saint-Michel' }],
            more: 2,
        },
    ],
    rollups: [
        {
            key: 'analyses',
            label: 'Analyses',
            count: 79,
            items: [{ uri: '61216', label: 'XRF', count: 5 }],
            more: 0,
            truncated: false,
        },
    ],
    preview: null,
    has_geometry: true,
    degraded: false,
    ...overrides,
});

let ViewModel;
let registration;

beforeAll(async () => {
    const spy = vi
        .spyOn(ko.components, 'register')
        .mockImplementation((name, config) => {
            registration = { name, config };
        });
    await import('./ms-summary-popup.js');
    spy.mockRestore();
    ViewModel = registration.config.viewModel;
});

beforeEach(() => {
    handles = [];
    acquireSummary.mockReset();
    acquireSummary.mockImplementation(() => newHandle());
    invalidateSummary.mockReset();
});

const build = (params = {}) =>
    new ViewModel({ resourceId: ID, surface: 'map', ...params });

/** Build the component and hand it one answer from the cache. */
const buildWith = async (result, params = {}) => {
    const vm = build(params);
    handles[handles.length - 1].settle(result);
    await flush();
    return vm;
};

describe('registration', () => {
    it('registers under the name both surfaces bind', () => {
        expect(registration.name).toBe('ms-summary-popup');
        expect(registration.config.viewModel).toBeTypeOf('function');
        expect(registration.config).toHaveProperty('template');
    });
});

describe('loading', () => {
    it('acquires the summary once and starts loading', () => {
        const vm = build();

        expect(acquireSummary).toHaveBeenCalledTimes(1);
        expect(acquireSummary).toHaveBeenCalledWith(ID);
        expect(vm.loading()).toBe(true);
        expect(vm.summary()).toBeNull();
        expect(vm.errorCode()).toBeNull();
    });

    it('unwraps an observable resourceId', () => {
        build({ resourceId: ko.observable(ID) });

        expect(acquireSummary).toHaveBeenCalledWith(ID);
    });

    it('shows the graph name in the title bar while loading', () => {
        const vm = build({ graphName: 'Document' });

        expect(vm.title()).toBe('Document');
        expect(vm.graphName()).toBe('Document');
    });

    it('follows a graph name the search map fills after construction', () => {
        const graphName = ko.observable('');
        const vm = build({ graphName });

        expect(vm.graphName()).toBe('');

        graphName('Document');

        expect(vm.title()).toBe('Document');
        expect(vm.graphName()).toBe('Document');
    });

    it('stops loading and publishes the payload', async () => {
        const vm = await buildWith({ status: 'ok', data: payload() });

        expect(vm.loading()).toBe(false);
        expect(vm.errorCode()).toBeNull();
        expect(vm.title()).toBe('Avranches. BM, Ms. 59');
        expect(vm.graphName()).toBe('Document');
        expect(vm.fields()).toHaveLength(2);
        expect(vm.rollups()).toHaveLength(1);
        expect(vm.hasGeometry()).toBe(true);
    });

    it('derives everything the template reads through pure computeds', async () => {
        const vm = await buildWith({ status: 'ok', data: payload() });

        ['title', 'graphName', 'fields', 'rollups', 'preview', 'spark', 'reportUrl'].forEach(
            (name) => {
                expect(ko.isPureComputed(vm[name])).toBe(true);
            }
        );
    });

    it('reports an empty configured payload', async () => {
        const vm = await buildWith({
            status: 'ok',
            data: payload({ fields: [], rollups: [], has_geometry: false }),
        });

        expect(vm.isEmpty()).toBe(true);
        expect(vm.emptyMessage()).toBe('No details to show.');
    });

    it('does not call a resource with fields empty', async () => {
        const vm = await buildWith({ status: 'ok', data: payload() });

        expect(vm.isEmpty()).toBe(false);
    });
});

describe('report URLs', () => {
    it('builds the resource report URL from arches.urls', async () => {
        const vm = await buildWith({ status: 'ok', data: payload() });

        expect(vm.reportUrl()).toBe(`/fr/report/${ID}`);
    });

    it('ignores a report URL the payload tries to supply', async () => {
        const vm = await buildWith({
            status: 'ok',
            data: payload({ links: { report: 'https://evil.example/pwn' } }),
        });

        expect(vm.reportUrl()).toBe(`/fr/report/${ID}`);
        expect(vm.reportUrl()).not.toContain('evil.example');
    });

    it('builds a linked resource URL from its id', async () => {
        const vm = await buildWith({ status: 'ok', data: payload() });

        expect(vm.reportUrlFor(PLACE_ID)).toBe(`/fr/report/${PLACE_ID}`);
    });

    it('refuses an id that is not a uuid', async () => {
        const vm = await buildWith({ status: 'ok', data: payload() });

        expect(vm.reportUrlFor('//evil.example/pwn')).toBeNull();
        expect(vm.reportUrlFor('javascript:alert(1)')).toBeNull();
        expect(vm.reportUrlFor(undefined)).toBeNull();
    });

    it('offers no map link in v1', async () => {
        const vm = await buildWith({ status: 'ok', data: payload() });

        expect(vm.mapUrl()).toBeNull();
    });
});

describe('refusals', () => {
    it.each([
        ['forbidden', 'You do not have permission to view this resource.'],
        ['notfound', 'This resource no longer exists.'],
        ['network', 'The summary could not be loaded.'],
    ])('renders %s as a message with no summary', async (status, message) => {
        const vm = await buildWith({ status });

        expect(vm.loading()).toBe(false);
        expect(vm.errorCode()).toBe(status);
        expect(vm.errorMessage()).toBe(message);
        expect(vm.summary()).toBeNull();
    });

    it('keeps the name of a degraded payload beside the warning', async () => {
        const vm = await buildWith({
            status: 'ok',
            data: { id: ID, name: 'Avranches. BM, Ms. 59', graph: { name: 'Document' }, degraded: true },
        });

        expect(vm.errorCode()).toBe('degraded');
        expect(vm.errorMessage()).toBe('Details are unavailable right now.');
        expect(vm.title()).toBe('Avranches. BM, Ms. 59');
        expect(vm.fields()).toEqual([]);
        expect(vm.isEmpty()).toBe(false);
    });

    it('refuses a missing resourceId without asking the server', () => {
        const vm = build({ resourceId: null });

        expect(acquireSummary).not.toHaveBeenCalled();
        expect(vm.loading()).toBe(false);
        expect(vm.errorCode()).toBe('notfound');
    });

    it('drops the failed entry and acquires again on retry', async () => {
        const vm = await buildWith({ status: 'network' });

        vm.retry();

        expect(handles[0].release).toHaveBeenCalledTimes(1);
        expect(invalidateSummary).toHaveBeenCalledWith(ID);
        expect(invalidateSummary).toHaveBeenCalledTimes(1);
        expect(acquireSummary).toHaveBeenCalledTimes(2);
        expect(vm.loading()).toBe(true);
        expect(vm.errorCode()).toBeNull();

        handles[1].settle({ status: 'ok', data: payload() });
        await flush();

        expect(vm.summary()).not.toBeNull();
        expect(vm.errorCode()).toBeNull();
    });

    it('gives the reference back before dropping the entry', async () => {
        const vm = await buildWith({ status: 'network' });
        const order = [];
        handles[0].release.mockImplementation(() => order.push('release'));
        invalidateSummary.mockImplementation(() => order.push('invalidate'));

        vm.retry();

        expect(order).toEqual(['release', 'invalidate']);
    });

    it('drops the answer of a reference retry replaced', async () => {
        const vm = await buildWith({ status: 'network' });

        vm.retry();
        handles[0].settle({ status: 'forbidden' });
        handles[1].settle({ status: 'ok', data: payload() });
        await flush();

        expect(vm.errorCode()).toBeNull();
        expect(vm.title()).toBe('Avranches. BM, Ms. 59');
    });
});

describe('unconfigured model', () => {
    it('falls back to the name and the map popup text', async () => {
        const vm = await buildWith({
            status: 'ok',
            data: {
                id: ID,
                configured: false,
                name: 'Ms. 12, fonds ancien',
                graph: { slug: 'person', name: 'Person' },
                map_popup: 'Ms. 12 — fonds ancien, Avranches',
            },
        });

        expect(vm.legacy()).toBe(true);
        expect(vm.mapPopup()).toBe('Ms. 12 — fonds ancien, Avranches');
        expect(vm.title()).toBe('Ms. 12, fonds ancien');
        expect(vm.fields()).toEqual([]);
        expect(vm.rollups()).toEqual([]);
        expect(vm.isEmpty()).toBe(false);
    });

    it('carries no map popup text on a configured payload', async () => {
        const vm = await buildWith({ status: 'ok', data: payload() });

        expect(vm.legacy()).toBe(false);
        expect(vm.mapPopup()).toBe('');
    });
});

describe('spectrum thumbnail', () => {
    it('hides the block when the payload carries no preview', async () => {
        const vm = await buildWith({ status: 'ok', data: payload() });

        expect(vm.spark()).toBeNull();
    });

    it('hands the binding the file id and a title', async () => {
        const vm = await buildWith({
            status: 'ok',
            data: payload({ preview: { file_id: 'file-1', label: 'FORS' } }),
        });

        expect(vm.spark()).toEqual({ fileId: 'file-1', title: 'FORS' });
        expect(vm.previewLabel()).toBe('Spectrum — FORS');
    });

    it('names the block even when the preview has no label', async () => {
        const vm = await buildWith({
            status: 'ok',
            data: payload({ preview: { file_id: 'file-1' } }),
        });

        expect(vm.spark()).toEqual({ fileId: 'file-1', title: '' });
        expect(vm.previewLabel()).toBe('Spectrum');
    });
});

describe('counters', () => {
    it('renders the overflow count through the translated pattern', () => {
        const vm = build();

        expect(vm.moreLabel(2)).toBe('+2');
    });

    it('joins plain values with a dash and tolerates a missing list', () => {
        const vm = build();

        expect(vm.joinValues(['1030-01', '1045-12'])).toBe('1030-01 – 1045-12');
        expect(vm.joinValues(undefined)).toBe('');
    });
});

describe('disposal', () => {
    it('releases the page cache reference', async () => {
        const vm = await buildWith({ status: 'ok', data: payload() });

        vm.dispose();

        expect(handles[0].release).toHaveBeenCalledTimes(1);
    });

    it('releases once when disposed twice', async () => {
        const vm = await buildWith({ status: 'ok', data: payload() });

        vm.dispose();
        vm.dispose();

        expect(handles[0].release).toHaveBeenCalledTimes(1);
    });

    it('ignores an answer that lands after disposal', async () => {
        const vm = build();

        vm.dispose();
        handles[0].settle({ status: 'ok', data: payload() });
        await flush();

        expect(vm.summary()).toBeNull();
        expect(vm.loading()).toBe(true);
    });

    it('lets the core helper sweep the computeds it derived', async () => {
        const vm = await buildWith({ status: 'ok', data: payload() });
        const swept = ['title', 'graphName', 'fields', 'rollups', 'spark'].map(
            (name) => vi.spyOn(vm[name], 'dispose')
        );

        vm.dispose();

        expect(vm.disposables).toBeUndefined();
        swept.forEach((spy) => expect(spy).toHaveBeenCalledTimes(1));
    });
});

describe('rendering', () => {
    beforeAll(() => {
        // Task 11 owns the real binding; here it only has to exist.
        ko.bindingHandlers.msSpark = { init: () => {} };
    });

    const render = (vm) => {
        const host = document.createElement('div');
        host.innerHTML = template;
        ko.applyBindings(vm, host);
        hosts.push(host);
        return host;
    };

    let hosts;

    beforeEach(() => {
        hosts = [];
    });

    afterEach(() => {
        hosts.forEach((host) => ko.cleanNode(host));
    });

    const textOf = (host, selector) =>
        [...host.querySelectorAll(selector)].map((node) => node.textContent.trim());

    it('renders the name, the model and the fields', async () => {
        const host = render(
            await buildWith({ status: 'ok', data: payload() }, { surface: 'iiif' })
        );

        expect(host.querySelector('.hover-feature-title').textContent).toBe(
            'Avranches. BM, Ms. 59'
        );
        expect(host.querySelector('.ms-summary-footer')).not.toBeNull();
        expect(host.querySelector('.hover-feature-metadata').textContent).toContain(
            'Document'
        );
        expect(textOf(host, '.ms-summary-fields dt')).toEqual(['Période', 'Lieu']);
        expect(textOf(host, '.ms-summary-fields .label-default')).toEqual([
            'Moyen Âge classique',
        ]);
    });

    it('links a field value to the report of its own resource', async () => {
        const host = render(await buildWith({ status: 'ok', data: payload() }));
        const link = host.querySelector('.ms-summary-fields a');

        expect(link.textContent).toBe('Le Mont-Saint-Michel');
        expect(link.getAttribute('href')).toBe(`/fr/report/${PLACE_ID}`);
    });

    it('leaves the title bar and the footer to the search map popup', async () => {
        const host = render(await buildWith({ status: 'ok', data: payload() }));

        expect(host.querySelector('.hover-feature-title')).toBeNull();
        expect(host.querySelector('.ms-summary-footer')).toBeNull();
        expect(host.querySelector('.ms-summary').classList).toContain(
            'ms-summary--embedded'
        );
        expect(textOf(host, '.ms-summary-fields dt')).toEqual(['Période', 'Lieu']);
    });

    it('separates several linked values without markup', async () => {
        const host = render(
            await buildWith({
                status: 'ok',
                data: payload({
                    fields: [
                        {
                            key: 'k',
                            label: 'Lieu',
                            style: 'link',
                            values: [
                                { id: PLACE_ID, label: 'Le Mont-Saint-Michel' },
                                { id: ID, label: 'Avranches' },
                            ],
                            more: 0,
                        },
                    ],
                }),
            })
        );
        const cell = host.querySelector('.ms-summary-fields dd');

        expect(cell.querySelectorAll('a')).toHaveLength(2);
        expect(cell.textContent.replace(/\s+/g, ' ').trim()).toBe(
            'Le Mont-Saint-Michel, Avranches'
        );
    });

    it('marks the values a field left out', async () => {
        const host = render(await buildWith({ status: 'ok', data: payload() }));

        expect(host.querySelector('.ms-summary-fields .text-muted').textContent).toBe(
            '+2'
        );
    });

    it('renders a rollup as a count, a label and its distinct values', async () => {
        const host = render(await buildWith({ status: 'ok', data: payload() }));
        const row = host.querySelector('.ms-summary-rollups li');

        expect(row.querySelector('a').getAttribute('href')).toBe(`/fr/report/${ID}`);
        expect(row.querySelector('strong').textContent).toBe('79');
        expect(row.textContent).toContain('Analyses');
        expect(textOf(row, '.label-default')).toEqual(['XRF']);
    });

    it('drops a field link whose id is not a uuid', async () => {
        const host = render(
            await buildWith({
                status: 'ok',
                data: payload({
                    fields: [
                        {
                            key: 'k',
                            label: 'Lieu',
                            style: 'link',
                            values: [{ id: '//evil.example/pwn', label: 'Ailleurs' }],
                            more: 0,
                        },
                    ],
                }),
            })
        );
        const link = host.querySelector('.ms-summary-fields a');

        expect(link.textContent).toBe('Ailleurs');
        expect(link.hasAttribute('href')).toBe(false);
    });

    it('joins the values of a plain field', async () => {
        const host = render(
            await buildWith({
                status: 'ok',
                data: payload({
                    fields: [
                        {
                            key: 'k',
                            label: 'Date',
                            style: 'date',
                            values: ['1030-01', '1045-12'],
                            more: 0,
                        },
                    ],
                }),
            })
        );

        expect(host.querySelector('.ms-summary-fields dd').textContent).toContain(
            '1030-01 – 1045-12'
        );
    });

    it('shows a refusal and offers the retry only on a network error', async () => {
        const forbidden = render(await buildWith({ status: 'forbidden' }));
        expect(forbidden.querySelector('.ms-summary-alert').textContent).toBe(
            'You do not have permission to view this resource.'
        );
        expect(forbidden.querySelector('button').style.display).toBe('none');
        expect(forbidden.querySelector('.ms-summary-fields')).toBeNull();

        const network = render(await buildWith({ status: 'network' }));
        expect(network.querySelector('button').style.display).not.toBe('none');
    });

    it('renders an unconfigured model as its name and map popup text', async () => {
        const host = render(
            await buildWith({
                status: 'ok',
                data: {
                    id: ID,
                    configured: false,
                    name: 'Ms. 12',
                    graph: { name: 'Person' },
                    map_popup: '<b>Ms. 12</b>',
                },
            })
        );
        const legacy = host.querySelector('.ms-summary-legacy');

        expect(legacy.textContent).toBe('<b>Ms. 12</b>');
        expect(legacy.querySelector('b')).toBeNull();
    });

    it('hands the spark binding the preview of the payload', async () => {
        const seen = [];
        ko.bindingHandlers.msSpark = {
            init: (element, valueAccessor) => seen.push(ko.unwrap(valueAccessor())),
        };
        const host = render(
            await buildWith({
                status: 'ok',
                data: payload({ preview: { file_id: 'file-1', label: 'FORS' } }),
            })
        );

        expect(seen).toEqual([{ fileId: 'file-1', title: 'FORS' }]);
        expect(host.querySelector('.ms-summary-spark').getAttribute('aria-label')).toBe(
            'Spectrum — FORS'
        );
    });

    it('shows the spinner while loading and nothing else', () => {
        const host = render(build());

        expect(host.querySelector('.ms-summary-loading')).not.toBeNull();
        expect(host.querySelector('.ms-summary').getAttribute('aria-busy')).toBeNull();
        expect(
            host.querySelector('.hover-feature-body').getAttribute('aria-busy')
        ).toBe('true');
        expect(host.querySelector('.ms-summary-fields')).toBeNull();
    });
});

describe('template', () => {
    it('never writes payload data as markup', () => {
        expect(template).not.toMatch(/\bhtml\s*:/);
        expect(template).not.toContain('innerHTML');
    });

    it('binds href only through the client-built URLs', () => {
        const hrefs = template.match(/href['"]?\s*:\s*[^,}]+/g) || [];

        expect(hrefs.length).toBeGreaterThan(0);
        hrefs.forEach((binding) => {
            expect(binding).toMatch(/reportUrl|mapUrl/);
        });
    });

    it('carries the dialog semantics screen readers need', () => {
        expect(template).toContain('role="dialog"');
        expect(template).toContain("'aria-label': title");
        expect(template).toContain('aria-live="polite"');
        expect(template).toContain("'aria-busy': loading");
    });
});
