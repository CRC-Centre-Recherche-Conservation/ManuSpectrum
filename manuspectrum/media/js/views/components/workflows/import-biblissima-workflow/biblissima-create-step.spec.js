/**
 * Vitest unit spec — biblissima-create-step.js (Tasks 3.5–3.7)
 *
 * Tests the new bulk create-all plumbing:
 *   - _mintClientId: minted + unique per item, plain field (not observable)
 *   - _buildCreatePayload: structure snapshot
 *   - createAll: fan-out by clientId → created/error + batchSummary
 *   - request-level failure → all still-creating items become error
 *   - dangling-dep error result lands on the right item (not on siblings)
 *   - batchSummaryText, dismissBatchSummary, retryAllFailed
 *
 * Note: this file lives under media/js/ so it executes but does NOT count
 * toward the coverage gate (coverage.include targets manuspectrum/src/).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ---- Module-level mocks (hoisted by vi.mock before imports) ----------------

vi.mock('knockout', () => {
    // Minimal KO mock: observables backed by closures.
    const makeObs = (init) => {
        let val = init;
        const obs = (...args) => {
            if (args.length > 0) val = args[0];
            return val;
        };
        obs.subscribe = vi.fn(() => ({ dispose: vi.fn() }));
        obs.peek = () => val;
        return obs;
    };

    const makeObsArr = (init) => {
        let val = Array.isArray(init) ? [...init] : [];
        const obs = (...args) => {
            if (args.length > 0) val = Array.isArray(args[0]) ? [...args[0]] : [];
            return val;
        };
        obs.subscribe = vi.fn(() => ({ dispose: vi.fn() }));
        obs.push = (item) => val.push(item);
        obs.filter = (fn) => val.filter(fn);
        obs.forEach = (fn) => val.forEach(fn);
        obs.every = (fn) => val.every(fn);
        obs.some = (fn) => val.some(fn);
        obs.valueHasMutated = vi.fn();
        return obs;
    };

    const makeComputed = (fn) => {
        const obs = () => fn();
        obs.subscribe = vi.fn(() => ({ dispose: vi.fn() }));
        return obs;
    };

    return {
        default: {
            observable: makeObs,
            observableArray: makeObsArr,
            computed: makeComputed,
            components: { register: vi.fn() },
            toJS: (item) => {
                const r = {};
                for (const k of Object.keys(item || {})) {
                    const v = item[k];
                    r[k] = typeof v === 'function' ? v() : v;
                }
                return r;
            },
            unwrap: (v) => (typeof v === 'function' ? v() : v),
        },
    };
});

vi.mock('arches', () => ({
    default: {
        translations: {
            biblissimaBatchSuccess: '{n} resources created',
            biblissimaBatchPartial: '{created} created · {failed} failed',
            biblissimaRetryAll: 'Retry all failed',
            biblissimaBatchError: 'Batch creation failed. Please retry.',
            biblissimaPending: 'Pending',
            biblissimaCreating: 'Creating...',
            biblissimaCreated: 'Created',
            biblissimaError: 'Error',
            biblissimaSkipped: 'Skipped',
            biblissimaDuplicate: 'Duplicate',
            biblissimaLinked: 'Linked',
            biblissimaSearchExisting: 'Search existing resource...',
            biblissimaLoadingEnriching: 'Enriching manuscript metadata…',
        },
        urls: {
            search_results: '/search/results',
            api_resources: (id) => `/api/resources/${id}`,
        },
    },
}));

vi.mock('bindings/select2-query', () => ({ default: {} }));
vi.mock('bindings/thumb-fallback', () => ({ default: {} }));
vi.mock('viewmodels/resource-instance-select', () => ({ default: vi.fn() }));
vi.mock(
    'templates/views/components/workflows/import-biblissima-workflow/biblissima-create-step.htm',
    () => ({ default: '<div></div>' })
);
vi.mock('./parentResolver', () => {
    // Use a real class: `new ParentResolver(...)` in Component mode must yield
    // an instance carrying the methods the init calls (resolveAll, allResolved,
    // parentIdFor, …). A `vi.fn().mockImplementation(() => ({...}))` does NOT
    // reliably expose those on the constructed instance.
    class ParentResolverMock {
        constructor() {
            this.totalCount = () => 0;
            this.unidentifiedItems = () => [];
            this.resolving = () => false;
            this.allResolved = () => true;
            this.resolvedCount = () => 0;
            this.parentIdFor = () => null;
            this.resolveAll = vi.fn().mockResolvedValue(undefined);
        }
    }
    return { default: ParentResolverMock };
});

// Import AFTER all mocks are in place.
import viewModel from './biblissima-create-step.js';

// ---- Helpers ---------------------------------------------------------------

/** Minimal params to instantiate the viewModel without real workflow context. */
const makeParams = (items = [], resourceType = 'Document') => ({
    form: null, // triggers ko.observable(false) fallback for `complete`
    configStepData: { resourceType, projectId: 'proj-123' },
    searchStepData: { selectedItems: items },
    value: vi.fn(),
});

/** A raw Biblissima cart item (plain data, before observable wrapping). */
const makeRawItem = (overrides = {}) => ({
    label: 'Test Manuscript',
    arkId: 'ark:/12345/test',
    shelfmark: 'BnF lat. 1',
    biblissimaQid: 'Q12345',
    manifestUrl: '',
    locationLabel: 'Paris (France)',
    collectionLabel: 'Bibliothèque nationale de France',
    parentInstitutionLabel: '',
    authorLabel: '',
    location: '',
    ifdataHash: '',     // empty → enrichStatus = 'na', no enrichment fetch
    typeValueId: '30931466-b4e0-4527-ac93-b7290e80084c',
    documentTypeValueId: '30931466-b4e0-4527-ac93-b7290e80084c',
    documentTypeIsFallback: false,
    ...overrides,
});

/**
 * Instantiate the viewModel with a controlled fetch stub, then drain the
 * background async init (resolveDependencies + checkDuplicates) so that
 * subsequent test fetch stubs intercept only what the test cares about.
 */
const makeViewModel = async (items = [], resourceType = 'Document') => {
    // Generic stub for the background init calls (check-duplicates etc.)
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() =>
        Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ results: [], resourceId: null }),
        })
    ));
    const vm = new viewModel(makeParams(items, resourceType));
    // Drain the async init queue (resolveDependencies awaits a fetch promise).
    await new Promise((resolve) => setTimeout(resolve, 0));
    return vm;
};

// ---- Tests -----------------------------------------------------------------

describe('biblissima-create-step', () => {
    afterEach(() => {
        vi.restoreAllMocks();
    });

    // =========================================================================
    // T1: _mintClientId — uniqueness + plain field
    // =========================================================================

    describe('_mintClientId / clientId per item', () => {
        it('mints a non-empty string clientId for each item', async () => {
            const vm = await makeViewModel([makeRawItem()]);
            const items = vm.items();
            expect(items).toHaveLength(1);
            expect(typeof items[0].clientId).toBe('string');
            expect(items[0].clientId.length).toBeGreaterThan(8);
        });

        it('mints a UNIQUE clientId for each item in the cart', async () => {
            const vm = await makeViewModel([
                makeRawItem({ label: 'Item A' }),
                makeRawItem({ label: 'Item B' }),
            ]);
            const items = vm.items();
            expect(items).toHaveLength(2);
            expect(items[0].clientId).not.toBe(items[1].clientId);
        });

        it('clientId is a plain field, NOT a KO observable', async () => {
            const vm = await makeViewModel([makeRawItem()]);
            const item = vm.items()[0];
            // Plain string — not a function / observable wrapper
            expect(typeof item.clientId).toBe('string');
        });

        it('clientId looks like a UUID (basic shape)', async () => {
            const vm = await makeViewModel([makeRawItem()]);
            const { clientId } = vm.items()[0];
            // Loose UUID pattern — allows any UUID version from the 3 fallback paths
            expect(clientId).toMatch(
                /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
            );
        });
    });

    // =========================================================================
    // T2: _buildCreatePayload — structure snapshot
    // =========================================================================

    describe('_buildCreatePayload', () => {
        it('returns the correct top-level payload structure', async () => {
            const vm = await makeViewModel([makeRawItem()]);
            const item = vm.items()[0];
            const payload = vm._buildCreatePayload(item);

            expect(payload).toHaveProperty('resourceType', 'Document');
            expect(payload).toHaveProperty('transactionId', null);
            expect(payload).toHaveProperty('biblissimaData');
            expect(payload).toHaveProperty('dependencies');
            expect(payload).toHaveProperty('conceptMappings');
        });

        it('dependencies always include the project id', async () => {
            const vm = await makeViewModel([makeRawItem()]);
            const item = vm.items()[0];
            const { dependencies } = vm._buildCreatePayload(item);
            expect(dependencies.project).toBe('proj-123');
        });

        it('honours options.transactionId', async () => {
            const vm = await makeViewModel([makeRawItem()]);
            const item = vm.items()[0];
            const { transactionId } = vm._buildCreatePayload(item, { transactionId: 'tx-abc' });
            expect(transactionId).toBe('tx-abc');
        });

        it('clientId is NOT embedded inside the payload object', async () => {
            // clientId is added by createAll as a sibling key ({clientId, ...payload})
            const vm = await makeViewModel([makeRawItem()]);
            const item = vm.items()[0];
            const payload = vm._buildCreatePayload(item);
            expect(Object.keys(payload)).not.toContain('clientId');
        });
    });

    // =========================================================================
    // T3: createAll fans results[] → created/error + batchSummary
    // =========================================================================

    describe('createAll — happy path fan-out', () => {
        it('fans a mixed result set (created + failed) back by clientId', async () => {
            const vm = await makeViewModel([
                makeRawItem({ label: 'MS A' }),
                makeRawItem({ label: 'MS B' }),
            ]);
            const [item0, item1] = vm.items();

            vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
                if (url === '/api/biblissima/create-all') {
                    return Promise.resolve({
                        ok: true,
                        json: () => Promise.resolve({
                            results: [
                                { clientId: item0.clientId, status: 'created', resourceId: 'res-001' },
                                { clientId: item1.clientId, status: 'failed', error: 'Manifest fetch failed' },
                            ],
                        }),
                    });
                }
                // create-resource calls (dep creation during _ensureDepsCreated)
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({ resourceId: 'dep-uuid', results: [] }),
                });
            }));

            await vm.createAll();

            expect(item0.status()).toBe('created');
            expect(item0.resourceId()).toBe('res-001');

            expect(item1.status()).toBe('error');
            expect(item1.errorMessage()).toBe('Manifest fetch failed');
        });

        it('sets batchSummary with correct created/failed counts', async () => {
            const vm = await makeViewModel([
                makeRawItem({ label: 'MS A' }),
                makeRawItem({ label: 'MS B' }),
            ]);
            const [item0, item1] = vm.items();

            vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
                if (url === '/api/biblissima/create-all') {
                    return Promise.resolve({
                        ok: true,
                        json: () => Promise.resolve({
                            results: [
                                { clientId: item0.clientId, status: 'created', resourceId: 'res-001' },
                                { clientId: item1.clientId, status: 'failed', error: 'Network error' },
                            ],
                        }),
                    });
                }
                return Promise.resolve({ ok: true, json: () => Promise.resolve({ results: [] }) });
            }));

            await vm.createAll();

            const summary = vm.batchSummary();
            expect(summary).not.toBeNull();
            expect(summary.created).toBe(1);
            expect(summary.failed).toBe(1);
        });

        it('resets creatingAll to false in finally (even on success)', async () => {
            const vm = await makeViewModel([makeRawItem()]);
            const [item0] = vm.items();

            vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
                if (url === '/api/biblissima/create-all') {
                    return Promise.resolve({
                        ok: true,
                        json: () => Promise.resolve({
                            results: [{ clientId: item0.clientId, status: 'created', resourceId: 'r-1' }],
                        }),
                    });
                }
                return Promise.resolve({ ok: true, json: () => Promise.resolve({ results: [] }) });
            }));

            await vm.createAll();
            expect(vm.creatingAll()).toBe(false);
        });
    });

    // =========================================================================
    // T4: request-level failure → all creating → error
    // =========================================================================

    describe('createAll — request-level failure', () => {
        it('flips all still-creating items to error on network exception', async () => {
            const vm = await makeViewModel([
                makeRawItem({ label: 'MS A' }),
                makeRawItem({ label: 'MS B' }),
            ]);
            const items = vm.items();

            vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
                if (url === '/api/biblissima/create-all') {
                    return Promise.reject(new Error('Network error'));
                }
                return Promise.resolve({ ok: true, json: () => Promise.resolve({ results: [] }) });
            }));

            await vm.createAll();

            items.forEach((i) => {
                expect(i.status()).toBe('error');
                expect(i.errorMessage()).toContain('Batch creation failed');
            });
        });

        it('flips all still-creating items to error on !resp.ok (e.g. 500)', async () => {
            const vm = await makeViewModel([makeRawItem()]);
            const [item0] = vm.items();

            vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
                if (url === '/api/biblissima/create-all') {
                    return Promise.resolve({
                        ok: false,
                        status: 500,
                        json: () => Promise.resolve({ error: 'Internal server error' }),
                    });
                }
                return Promise.resolve({ ok: true, json: () => Promise.resolve({ results: [] }) });
            }));

            await vm.createAll();

            expect(item0.status()).toBe('error');
            const summary = vm.batchSummary();
            expect(summary.failed).toBe(1);
            expect(summary.created).toBe(0);
        });

        it('resets creatingAll to false in finally even on failure', async () => {
            const vm = await makeViewModel([makeRawItem()]);

            vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connection refused')));

            await vm.createAll();
            expect(vm.creatingAll()).toBe(false);
        });
    });

    // =========================================================================
    // T5: dangling-dep error fan-out — lands on the right item only
    // =========================================================================

    describe('createAll — dangling-dep error fan case', () => {
        it('maps a dangling-dep "failed" result to the exact item by clientId', async () => {
            const vm = await makeViewModel([
                makeRawItem({ label: 'Good MS' }),
                makeRawItem({ label: 'Bad MS' }),
            ]);
            const [item0, item1] = vm.items();

            const danglingMsg =
                'Dependency abc-123-def for "currentLocation" does not exist; ' +
                'cannot link a dangling relationship.';

            vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
                if (url === '/api/biblissima/create-all') {
                    return Promise.resolve({
                        ok: true,
                        json: () => Promise.resolve({
                            results: [
                                { clientId: item0.clientId, status: 'created', resourceId: 'res-ok' },
                                { clientId: item1.clientId, status: 'failed', error: danglingMsg },
                            ],
                        }),
                    });
                }
                return Promise.resolve({ ok: true, json: () => Promise.resolve({ results: [] }) });
            }));

            await vm.createAll();

            // item0 must be created
            expect(item0.status()).toBe('created');
            expect(item0.resourceId()).toBe('res-ok');

            // item1 must be error with the exact backend message
            expect(item1.status()).toBe('error');
            expect(item1.errorMessage()).toBe(danglingMsg);

            // item0 must NOT have any error message (not cross-contaminated)
            expect(item0.errorMessage()).toBe('');
        });
    });

    // =========================================================================
    // T6: batchSummaryText computed interpolation
    // =========================================================================

    describe('batchSummaryText', () => {
        it('returns interpolated success text when failed = 0', async () => {
            const vm = await makeViewModel([]);
            vm.batchSummary({ created: 5, failed: 0 });
            expect(vm.batchSummaryText()).toBe('5 resources created');
        });

        it('returns interpolated partial text when failed > 0', async () => {
            const vm = await makeViewModel([]);
            vm.batchSummary({ created: 3, failed: 2 });
            expect(vm.batchSummaryText()).toBe('3 created · 2 failed');
        });

        it('returns empty string when batchSummary is null', async () => {
            const vm = await makeViewModel([]);
            vm.batchSummary(null);
            expect(vm.batchSummaryText()).toBe('');
        });
    });

    // =========================================================================
    // T7: dismissBatchSummary + retryAllFailed
    // =========================================================================

    describe('dismissBatchSummary', () => {
        it('sets batchSummary to null', async () => {
            const vm = await makeViewModel([]);
            vm.batchSummary({ created: 2, failed: 0 });
            vm.dismissBatchSummary();
            expect(vm.batchSummary()).toBeNull();
        });
    });

    describe('retryAllFailed', () => {
        it('resets error items to pending and clears errorMessage', async () => {
            const vm = await makeViewModel([makeRawItem()]);
            const [item] = vm.items();

            item.status('error');
            item.errorMessage('Some failure message');
            vm.batchSummary({ created: 0, failed: 1 });

            // Spy on createAll to prevent actual network calls
            const spy = vi.spyOn(vm, 'createAll').mockResolvedValue(undefined);

            vm.retryAllFailed();

            expect(item.status()).toBe('pending');
            expect(item.errorMessage()).toBe('');
        });

        it('clears batchSummary before re-running createAll', async () => {
            const vm = await makeViewModel([makeRawItem()]);
            vm.batchSummary({ created: 0, failed: 1 });

            vi.spyOn(vm, 'createAll').mockResolvedValue(undefined);

            vm.retryAllFailed();

            expect(vm.batchSummary()).toBeNull();
        });

        it('calls createAll after resetting items', async () => {
            const vm = await makeViewModel([makeRawItem()]);
            const [item] = vm.items();
            item.status('error');

            const spy = vi.spyOn(vm, 'createAll').mockResolvedValue(undefined);

            vm.retryAllFailed();

            expect(spy).toHaveBeenCalledOnce();
        });
    });

    // =========================================================================
    // Stuck-loading regression: a Component item still enriching must block its
    // Create button AND explain WHY in the tooltip (not an empty "Waiting for:")
    // even when its parent Document and related-resource deps are all resolved.
    // Root cause was a dead IIIF host leaving enrichStatus stuck on 'loading';
    // unresolvedDepsLabel didn't mirror itemDepsResolved's enrichStatus guard.
    // =========================================================================

    describe('unresolvedDepsLabel — enrichStatus guard', () => {
        const makeComponentItem = (enrichState) => ({
            status: () => 'pending',
            enrichStatus: () => enrichState,
            showSuggestions: () => false,
            suggestions: () => [],
            location: '',
            locationLabel: '',
            collectionLabel: '',
            parentInstitutionLabel: '',
            authorLabel: '',
            manuscript: 'Abbeville. Bibliothèque municipale, FA 16 D 281',
            shelfmark: 'FA 16 D 281',
            portalHash: '',
            biblissimaQid: 'Q203781',
        });

        it('surfaces "Enriching…" (never an empty tooltip) while a Component item is still loading, even with parent + deps resolved', async () => {
            const vm = await makeViewModel([], 'Component');
            vm.dependencies([]); // no related-resource deps
            vm.parentResolver.parentIdFor = () => 'parent-xyz'; // parent resolved
            const item = makeComponentItem('loading');

            // Blocked...
            expect(vm.canCreateItem(item)).toBe(false);
            // ...and the tooltip explains WHY (not empty).
            const label = vm.unresolvedDepsLabel(item);
            expect(label).not.toBe('');
            expect(label).toContain('Enriching');
        });

        it('is empty and the item is creatable once enrichment is done and everything else resolved', async () => {
            const vm = await makeViewModel([], 'Component');
            vm.dependencies([]);
            vm.parentResolver.parentIdFor = () => 'parent-xyz';
            const item = makeComponentItem('done');

            expect(vm.unresolvedDepsLabel(item)).toBe('');
            expect(vm.canCreateItem(item)).toBe(true);
        });
    });
});
