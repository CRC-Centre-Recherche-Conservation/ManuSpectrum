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
    default: {
        translations: { biblissimaConceptInputTooLong: 'Query too long ({n} characters max)' },
        urls: {},
        activeLanguage: 'en',
    },
}));
vi.mock('nouislider', () => ({ default: { create: vi.fn() } }));

const { SUGGEST_URL, generateArchesURL } = vi.hoisted(() => {
    const url = '/mocked/biblissima-suggest';
    return { SUGGEST_URL: url, generateArchesURL: vi.fn(() => url) };
});

vi.mock('@/arches/utils/generate-arches-url.ts', () => ({ generateArchesURL }));

import viewModel from './biblissima-search-step.js';
import { SUGGEST_MAX_INPUT_LENGTH } from '../../widgets/biblissima-concept-utils.js';

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

describe('biblissima-search-step suggest selects', () => {
    it('send the same normalised query as the concept widget', () => {
        const { vm } = build();
        expect(vm.descriptorSelectConfig.ajax.data({ term: ' saint   jero ' }))
            .toEqual({ q: 'saint jero', type: 'descriptor', lang: 'fr' });
        expect(vm.manuscriptComponentSelectConfig.ajax.data({ term: 'latin ' }))
            .toEqual({ q: 'latin', type: 'manuscript', lang: 'fr', limit: 15 });
    });

    it('reach the suggest endpoint through its route name', () => {
        generateArchesURL.mockClear();
        const { vm } = build();
        expect(generateArchesURL).toHaveBeenCalledWith('manuspectrum:biblissima-suggest');
        expect(vm.descriptorSelectConfig.ajax.url).toBe(SUGGEST_URL);
        expect(vm.manuscriptComponentSelectConfig.ajax.url).toBe(SUGGEST_URL);
    });

    it('stop at the suggest endpoint length limit and say why', () => {
        const { vm } = build();
        expect(SUGGEST_MAX_INPUT_LENGTH).toBe(100);
        [vm.descriptorSelectConfig, vm.manuscriptComponentSelectConfig].forEach((config) => {
            expect(config.maximumInputLength).toBe(SUGGEST_MAX_INPUT_LENGTH);
            expect(config.language.inputTooLong({ maximum: SUGGEST_MAX_INPUT_LENGTH }))
                .toBe('Query too long (100 characters max)');
        });
    });
});
