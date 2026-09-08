/**
 * Vitest unit spec — viewmodels/afs-instrument.js subscription ownership.
 *
 * The viewmodel is applied to a consumer's `this` (xy-reader.js), and the seven
 * chart-formatting observables it subscribes to live on `params.state`, which
 * Arches hangs off the module-level `fileFormatRenderers` singleton. They
 * outlive every renderer instance, so the subscriptions have to be handed to
 * the consumer's disposables whatever order it builds in.
 *
 * Note: this file lives under media/js/viewmodels/, which coverage.include does
 * not target, so it executes without touching the coverage gate.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import ko from 'knockout';

import AfsInstrumentViewModel from './afs-instrument.js';

const RENDERER_ID = 'e1e0e1a7-2a1c-4b3f-9c4e-9f0d3c2b1a00';

// The observables the viewmodel mirrors into localStorage.
const FORMATTING_KEYS = [
    'chartTitle',
    'titleSize',
    'xAxisLabel',
    'xAxisLabelSize',
    'yAxisLabel',
    'yAxisLabelSize',
    'yAxisRightLabel',
];

// 'render' and 'parse' kick off the AJAX load; the panel context does not.
const buildParams = (state) => ({
    state: state,
    context: 'tab-contents',
    displayContent: {
        name: 'spectrum.csv',
        url: '/files/spectrum.csv',
        type: 'text/plain',
        renderer: { id: RENDERER_ID },
        validRenderer: ko.observable(true),
    },
});

describe('AfsInstrumentViewModel disposables', () => {
    let state;

    beforeEach(() => {
        window.localStorage.clear();
        state = {};
    });

    it('hands its formatting subscriptions to the array the consumer owns', () => {
        const disposables = [];
        const host = { disposables: disposables };

        AfsInstrumentViewModel.call(host, buildParams(state));

        expect(host.disposables).toBe(disposables);
        expect(disposables).toHaveLength(FORMATTING_KEYS.length);
    });

    it('creates the array when the consumer has not yet', () => {
        const host = {};

        AfsInstrumentViewModel.call(host, buildParams(state));

        expect(host.disposables).toHaveLength(FORMATTING_KEYS.length);
    });

    it('keeps entries a consumer pushed before applying it', () => {
        const earlier = ko.observable().subscribe(() => {});
        const host = { disposables: [earlier] };

        AfsInstrumentViewModel.call(host, buildParams(state));

        expect(host.disposables[0]).toBe(earlier);
    });

    it('releases the shared state observables once disposed', () => {
        const host = {};
        AfsInstrumentViewModel.call(host, buildParams(state));
        FORMATTING_KEYS.forEach((key) => {
            expect(state[key].getSubscriptionsCount()).toBeGreaterThan(0);
        });

        host.disposables.forEach((disposable) => disposable.dispose());

        FORMATTING_KEYS.forEach((key) => {
            expect(state[key].getSubscriptionsCount()).toBe(0);
        });
    });

    it('leaves a second instance subscribed when the first is disposed', () => {
        const chart = {};
        const panel = {};
        AfsInstrumentViewModel.call(chart, buildParams(state));
        AfsInstrumentViewModel.call(panel, buildParams(state));

        chart.disposables.forEach((disposable) => disposable.dispose());

        expect(state.chartTitle.getSubscriptionsCount()).toBe(1);
    });
});
