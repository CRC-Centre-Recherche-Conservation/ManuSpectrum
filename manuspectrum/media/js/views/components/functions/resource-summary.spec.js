/**
 * Vitest unit spec — views/components/functions/resource-summary.js.
 *
 * The Knockout shell of the summary configuration form: what it hands the Vue
 * application and what its `detached` callback does to the function manager.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

vi.mock('viewmodels/function-view-model', () => ({
    // The core viewmodel copies the applied function's graph id onto `this`.
    default: function (params) {
        this.graphid = params.graphid;
    },
}));

const { createVueApplication, mounted } = vi.hoisted(() => {
    const mounted = { app: null, props: null };
    return {
        mounted,
        createVueApplication: vi.fn(({ initialProps }) => {
            mounted.props = initialProps;
            mounted.app = { mount: vi.fn(), unmount: vi.fn() };
            return Promise.resolve(mounted.app);
        }),
    };
});

vi.mock('@/arches_vue_components/application', () => ({ createVueApplication }));
vi.mock('@/manuspectrum/functions/SummaryConfigForm/SummaryConfigForm.vue', () => ({
    default: {},
}));
vi.mock('templates/views/components/functions/resource-summary.htm', () => ({
    default: '<div></div>',
}));

let ViewModel;

beforeAll(async () => {
    const spy = vi.spyOn(ko.components, 'register').mockImplementation((name, config) => {
        ViewModel = config.viewModel;
    });
    await import('./resource-summary.js');
    spy.mockRestore();
});

afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
});

function functionManagerPage(applied) {
    const root = {
        appliedFunctionList: { items: ko.observableArray([{ id: 'other' }, applied]) },
        toggleFunctionLibrary: vi.fn(),
        navigate: vi.fn(),
    };
    const host = document.createElement('div');
    host.id = 'summary-config-g-1';
    document.body.appendChild(host);
    vi.spyOn(ko, 'contextFor').mockReturnValue({ $root: root });
    return root;
}

describe('resource-summary shell', () => {
    it('hands the graph id and a detached callback to the Vue application', () => {
        new ViewModel({ graphid: 'g-1' });

        expect(createVueApplication).toHaveBeenCalled();
        expect(mounted.props.graphid).toBe('g-1');
        expect(typeof mounted.props.onDetached).toBe('function');
    });

    it('drops the entry from the function manager before reloading the page', () => {
        const applied = { id: 'row-1', graphid: 'g-1' };
        const root = functionManagerPage(applied);
        new ViewModel(applied);

        mounted.props.onDetached();

        expect(root.appliedFunctionList.items()).toEqual([{ id: 'other' }]);
        expect(root.toggleFunctionLibrary).toHaveBeenCalledTimes(1);
        expect(root.navigate).toHaveBeenCalledWith(
            window.location.pathname + window.location.search
        );
        const order = [root.toggleFunctionLibrary, root.navigate].map(
            (fn) => fn.mock.invocationCallOrder[0]
        );
        expect(order[0]).toBeLessThan(order[1]);
    });

    it('falls back to a full reload when the page context is not the function manager', () => {
        const reload = vi.fn();
        vi.spyOn(ko, 'contextFor').mockReturnValue({ $root: {} });
        const host = document.createElement('div');
        host.id = 'summary-config-g-1';
        document.body.appendChild(host);
        const original = window.location;
        delete window.location;
        window.location = { ...original, reload };
        try {
            new ViewModel({ graphid: 'g-1' });
            mounted.props.onDetached();
        } finally {
            window.location = original;
        }

        expect(reload).toHaveBeenCalledTimes(1);
    });
});
