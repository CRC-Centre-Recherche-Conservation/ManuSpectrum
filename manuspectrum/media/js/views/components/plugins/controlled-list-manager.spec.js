/**
 * Vitest unit spec — controlled-list-manager.js (shadow of
 * arches_controlled_lists 1.2.0) Vue application lifecycle.
 *
 * The Knockout component owns the Vue app it mounts: it keeps the handle,
 * unmounts it on dispose, and never mounts an app whose Knockout host is
 * already gone (the application is created asynchronously).
 *
 * Note: this file lives under media/js/views/components/, which coverage.include
 * does not target, so it executes without touching the coverage gate.
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

const createVueApplication = vi.hoisted(() => vi.fn());

vi.mock('@primeuix/themes', () => ({
    definePreset: vi.fn(() => ({})),
    palette: vi.fn(() => ({})),
}));
vi.mock('@/arches/themes/default.ts', () => ({
    ArchesPreset: { primitive: { arches: { blue: {} } } },
    DEFAULT_THEME: { theme: {} },
}));
vi.mock('@/arches_controlled_lists/routes.ts', () => ({ routes: [] }));
vi.mock('@/arches_controlled_lists/plugins/ControlledListManager.vue', () => ({ default: {} }));
vi.mock('@/arches_vue_components/application', () => ({ createVueApplication }));
vi.mock('vue-router', () => ({
    createRouter: vi.fn(() => ({ name: 'router' })),
    createWebHistory: vi.fn(() => ({})),
}));

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

let ViewModel;

beforeAll(async () => {
    const register = vi.spyOn(ko.components, 'register').mockImplementation(() => {});
    await import('./controlled-list-manager.js');
    expect(register).toHaveBeenCalledWith('controlled-list-manager', expect.any(Object));
    ViewModel = register.mock.calls[0][1].viewModel;
    register.mockRestore();
});

describe('controlled-list-manager viewModel', () => {
    let app;

    beforeEach(() => {
        app = { use: vi.fn(), mount: vi.fn(), unmount: vi.fn() };
        createVueApplication.mockReset();
    });

    it('mounts the Vue app with the router once it is created', async () => {
        createVueApplication.mockResolvedValue(app);

        const vm = new ViewModel();
        await flush();

        expect(app.use).toHaveBeenCalledWith({ name: 'router' });
        expect(app.mount).toHaveBeenCalledWith('#controlled-list-manager-mounting-point');
        expect(vm.vueApp).toBe(app);
    });

    it('unmounts the Vue app exactly once on dispose', async () => {
        createVueApplication.mockResolvedValue(app);

        const vm = new ViewModel();
        await flush();
        vm.dispose();
        vm.dispose();

        expect(app.unmount).toHaveBeenCalledTimes(1);
        expect(vm.vueApp).toBeNull();
    });

    it('never mounts an app whose host was disposed before creation finished', async () => {
        let resolve;
        createVueApplication.mockReturnValue(new Promise((r) => { resolve = r; }));

        const vm = new ViewModel();
        vm.dispose();
        resolve(app);
        await flush();

        expect(app.mount).not.toHaveBeenCalled();
        expect(app.unmount).not.toHaveBeenCalled();
        expect(vm.vueApp).toBeNull();
    });
});
