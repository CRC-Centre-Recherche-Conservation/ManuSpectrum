/**
 * Vitest unit spec — utils/map-popup-provider.js (shadow of the Arches core
 * provider).
 *
 * The shadow owns two members and inherits the rest, so the cases are the two
 * it owns — our template is what the popup fetches, and a click hands the
 * summary module the resources it is about to offer — plus the guarantee that
 * the spread leaves the core's members, `findPopupFeatureById` included,
 * reachable through `this` when Arches binds them to our object.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

const TEMPLATE_URL = 'templates/views/components/ms-map-popup.htm';

const { coreProvider, attachMapboxPopupCleanup, warmSummaryCache } = vi.hoisted(() => ({
    coreProvider: {
        isFeatureClickable: vi.fn(() => true),
        getPopupTemplate: vi.fn(() => '<core-template/>'),
        processData: vi.fn((features) => features),
        sendFeatureToMapFilter: vi.fn(),
        showFilterByFeature(popupFeatureObject) {
            return this.findPopupFeatureById(popupFeatureObject) !== null;
        },
        findPopupFeatureById: vi.fn(() => null),
    },
    attachMapboxPopupCleanup: vi.fn((data) => data),
    warmSummaryCache: vi.fn(),
}));

vi.mock('arches/arches/app/media/js/utils/map-popup-provider', () => ({
    default: coreProvider,
}));

vi.mock('templates/views/components/ms-map-popup.htm', () => ({
    default: 'templates/views/components/ms-map-popup.htm',
}));

vi.mock('utils/summary-popup', () => ({
    attachMapboxPopupCleanup,
    warmSummaryCache,
}));

import provider from './map-popup-provider.js';

const requests = [];

class FakeXMLHttpRequest {
    constructor() {
        this.responseText = '';
        requests.push(this);
    }

    open(method, url, async) {
        this.method = method;
        this.url = url;
        this.async = async;
    }

    send() {
        this.responseText = '<div class="ms-popup"></div>';
    }
}

const feature = (resourceinstanceid) => ({ resourceinstanceid });

beforeEach(() => {
    requests.length = 0;
    vi.clearAllMocks();
    vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest);
});

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('getPopupTemplate', () => {
    it('fetches the project template synchronously and returns its body', () => {
        const markup = provider.getPopupTemplate();

        expect(requests).toHaveLength(1);
        expect(requests[0].method).toBe('GET');
        expect(requests[0].url).toBe(TEMPLATE_URL);
        expect(requests[0].async).toBe(false);
        expect(markup).toBe('<div class="ms-popup"></div>');
    });

    it('never falls through to the core template', () => {
        provider.getPopupTemplate();

        expect(coreProvider.getPopupTemplate).not.toHaveBeenCalled();
    });
});

describe('processData', () => {
    it('gives the popup its teardown before warming the cache', () => {
        provider.processData({ popupFeatures: [feature('a'), feature('b')] });

        expect(attachMapboxPopupCleanup).toHaveBeenCalledTimes(1);
        expect(warmSummaryCache).toHaveBeenCalledTimes(1);
        expect(attachMapboxPopupCleanup.mock.invocationCallOrder[0]).toBeLessThan(
            warmSummaryCache.mock.invocationCallOrder[0],
        );
    });

    it('hands the cleanup the data it was called with', () => {
        const data = { popupFeatures: [feature('a')] };

        provider.processData(data);

        expect(attachMapboxPopupCleanup).toHaveBeenCalledWith(data);
    });

    it('warms the cache with the ids of the features of the click', () => {
        provider.processData({
            popupFeatures: [feature('a'), { resourceinstanceid: ko.observable('b') }],
        });

        expect(warmSummaryCache).toHaveBeenCalledWith(['a', 'b']);
    });

    it('leaves out the features that carry no resource id', () => {
        provider.processData({
            popupFeatures: [
                feature('a'),
                { resourceinstanceid: ko.observable(false) },
                feature(undefined),
                feature(''),
            ],
        });

        expect(warmSummaryCache).toHaveBeenCalledWith(['a']);
    });

    it('warms nothing when the click carries no features', () => {
        provider.processData({});

        expect(warmSummaryCache).toHaveBeenCalledWith([]);
    });

    it('returns the data it was handed', () => {
        const data = { popupFeatures: [feature('a')] };

        expect(provider.processData(data)).toBe(data);
    });
});

describe('the members the shadow does not own', () => {
    it('keeps the core implementation', () => {
        expect(provider.isFeatureClickable).toBe(coreProvider.isFeatureClickable);
        expect(provider.sendFeatureToMapFilter).toBe(coreProvider.sendFeatureToMapFilter);
        expect(provider.findPopupFeatureById).toBe(coreProvider.findPopupFeatureById);
    });

    it('keeps findPopupFeatureById reachable through this', () => {
        const popupFeatureObject = { feature: { properties: { featureid: 'f' } } };
        coreProvider.findPopupFeatureById.mockReturnValueOnce({ id: 'f' });

        expect(provider.showFilterByFeature(popupFeatureObject)).toBe(true);
        expect(coreProvider.findPopupFeatureById).toHaveBeenCalledWith(popupFeatureObject);
    });
});
