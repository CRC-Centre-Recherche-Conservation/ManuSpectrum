/**
 * Vitest unit spec — biblissima-search-step.js teardown.
 *
 * Knockout rebuilds the step on every workflow save, so whatever the step
 * started (the 1 Hz loading timer, background page fetches, the noUiSlider,
 * the computed that drives `form.complete`) must stop in `dispose()`.
 *
 * Note: this file lives under media/js/views/components/, which coverage.include
 * does not target, so it executes without touching the coverage gate.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

vi.mock('arches', () => ({
    default: { translations: {}, urls: {}, activeLanguage: 'en' },
}));
vi.mock('nouislider', () => ({ default: { create: vi.fn() } }));

import viewModel from './biblissima-search-step.js';

const build = (overrides = {}) => {
    const params = {
        form: { complete: ko.observable(false) },
        value: ko.observable(null),
        configStepData: {},
        ...overrides,
    };
    return { vm: new viewModel(params), params };
};

describe('biblissima-search-step dispose', () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('stops the loading timer', () => {
        const { vm } = build();
        vm.searching(true);
        vi.advanceTimersByTime(2000);
        expect(vm.loadingElapsed()).toBe(2);

        vm.dispose();
        vi.advanceTimersByTime(3000);

        expect(vm._loadingTimer).toBeNull();
        expect(vm.loadingElapsed()).toBe(0);
    });

    it('aborts in-flight background page loads', () => {
        const { vm } = build();
        const controller = new AbortController();
        vm._pageLoadAbort = controller;

        vm.dispose();

        expect(controller.signal.aborted).toBe(true);
        expect(vm._pageLoadAbort).toBeNull();
    });

    it('destroys the date slider once', () => {
        const { vm } = build();
        const slider = { destroy: vi.fn() };
        vm._slider = slider;

        vm.dispose();
        vm.dispose();

        expect(slider.destroy).toHaveBeenCalledTimes(1);
    });

    it('flushes a pending persist instead of dropping it', () => {
        const { vm, params } = build();
        vm.cart.push({ id: 'item-1' });
        expect(params.value()).toBeNull();

        vm.dispose();

        expect(params.value()).not.toBeNull();
        expect(params.value().selectedItems).toHaveLength(1);
    });

    it('stops driving form.complete after dispose', () => {
        const complete = ko.observable(false);
        const { vm } = build({ form: { complete } });
        vm.cart.push({ id: 'item-1' });
        expect(complete()).toBe(true);

        vm.dispose();
        vm.cart.removeAll();

        expect(complete()).toBe(true);
    });
});
