/**
 * Vitest unit spec — iiif-viewer.js (project wrapper over the core viewer).
 *
 * The wrapper carries one rule and one side effect: every host that does not
 * pass `onEachFeature` gets the summary-popup binder on the read-only
 * annotation layer, and the 'iiif-viewer' Knockout component is re-registered
 * so the hosts that resolve it by name reach the wrapper too. The core
 * viewmodel is mocked: it is applied to `this`, which the third test pins.
 *
 * Note: this file lives under media/js/views/components/, which coverage.include
 * does not target, so it executes without touching the coverage gate.
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

vi.mock('arches/arches/app/media/js/views/components/iiif-viewer', () => ({
    default: vi.fn(function (params) {
        this.received = params;
    }),
}));

vi.mock('utils/summary-popup', () => ({
    bindLeafletSummaryPopup: vi.fn(),
}));

vi.mock('views/components/ms-summary-popup', () => ({}));

import CoreIIIFViewerViewmodel from 'arches/arches/app/media/js/views/components/iiif-viewer';
import { bindLeafletSummaryPopup } from 'utils/summary-popup';

let IIIFViewerViewmodel;
let registration;
let unregistered;

beforeAll(async () => {
    const unregisterSpy = vi
        .spyOn(ko.components, 'unregister')
        .mockImplementation((name) => {
            unregistered = name;
        });
    const registerSpy = vi
        .spyOn(ko.components, 'register')
        .mockImplementation((name, config) => {
            registration = { name, config };
        });
    const module = await import('./iiif-viewer.js');
    registerSpy.mockRestore();
    unregisterSpy.mockRestore();
    IIIFViewerViewmodel = module.default;
});

describe('iiif-viewer wrapper', () => {
    it('hands the summary popup binder to the core viewmodel', () => {
        const params = { manifest: 'm' };
        const viewModel = new IIIFViewerViewmodel(params);

        expect(viewModel.received.onEachFeature).toBe(bindLeafletSummaryPopup);
        expect(CoreIIIFViewerViewmodel).toHaveBeenCalled();
    });

    it("keeps the host's own onEachFeature", () => {
        const onEachFeature = vi.fn();
        const viewModel = new IIIFViewerViewmodel({ onEachFeature });

        expect(viewModel.received.onEachFeature).toBe(onEachFeature);
        expect(viewModel.received.onEachFeature).not.toBe(bindLeafletSummaryPopup);
    });

    it('applies the core viewmodel to its own instance', () => {
        const viewModel = new IIIFViewerViewmodel({});

        expect(CoreIIIFViewerViewmodel.mock.instances.at(-1)).toBe(viewModel);
    });

    it('re-registers the iiif-viewer component on the wrapper', () => {
        expect(unregistered).toBe('iiif-viewer');
        expect(registration.name).toBe('iiif-viewer');
        expect(registration.config.viewModel).toBe(IIIFViewerViewmodel);
    });
});
