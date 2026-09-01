/**
 * Vitest unit spec — file-widget-xy.js shared chart registry.
 *
 * One node's files share a single Plotly chart, so one configuration governs
 * its axes and its view control. When the files disagree, that configuration
 * describes only some of them — and the view control would then offer a lens
 * chosen for one instrument family over another's data.
 *
 * Note: this file lives under media/js/viewmodels/, which coverage.include does
 * not target, so it executes without touching the coverage gate.
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

const FORS_ID = 'c0000000-0000-4000-8000-000000000001';
const XRF_ID = 'c0000000-0000-4000-8000-000000000002';
const NODE_ID = 'c0000000-0000-4000-8000-000000000003';

vi.mock('arches', () => ({
    default: {
        translations: {
            data: 'Data',
            xAxis: 'X Axis',
            yAxis: 'Y Axis',
            xyMixedConfigurations: 'These files use different configurations.',
        },
    },
}));

vi.mock('viewmodels/file-widget', () => ({
    default: function FileWidgetViewModel() {
        // What the widget actually uses from its base: a file list, a place to
        // register computeds for disposal, and the URL resolver it downloads
        // through.
        this.uploadedFiles = ko.observableArray([]);
        this.disposables = [];
        this.getFileUrl = (url) => url;
    },
}));

vi.mock('utils/dispose', () => ({ default: vi.fn() }));

vi.mock('jquery', () => ({
    default: Object.assign(
        () => ({ on: vi.fn(), off: vi.fn() }),
        { ajax: vi.fn(async () => '350,10\n351,20\n352,30'), off: vi.fn() }
    ),
}));

vi.mock('utils/renderer-cache', () => ({
    parseOverrides: () => ({}),
    getRendererConfig: vi.fn(async () => ({
        configs: [
            {
                configid: FORS_ID,
                config: {
                    presetKey: 'fors',
                    display: { yAxisLabel: 'Reflectance (0-1)' },
                },
            },
            {
                configid: XRF_ID,
                config: {
                    presetKey: 'xrf',
                    display: { yAxisLabel: 'Counts' },
                },
            },
        ],
    })),
}));

let FileWidgetXY;
beforeAll(async () => {
    FileWidgetXY = (await import('./file-widget-xy.js')).default;
});

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const entryFor = (configId, widget) => ({
    _widget: widget,
    file: { rendererConfig: configId, parsingOverrides: undefined, url: '/f.csv' },
    fileName: 'spectrum.csv',
    parsed: ko.observable(null),
    colorIndex: 0,
    selected: ko.observable(true),
    loading: ko.observable(true),
    error: ko.observable(null),
});

describe('a chart whose files disagree', () => {
    let vm;

    beforeEach(() => {
        vm = new FileWidgetXY({ node: { nodeid: NODE_ID + Math.random() } });
    });

    it('takes its axes from the one configuration when they agree', async () => {
        await vm._loadEntryData([entryFor(FORS_ID, vm), entryFor(FORS_ID, vm)]);
        await flush();

        expect(vm.mixedConfigurations()).toBe(false);
        expect(vm.storedConfig()).not.toBeNull();
        expect(vm.chartYAxisLabel()).toBe('Reflectance (0-1)');
    });

    it('stops claiming a configuration once a second one disagrees', async () => {
        await vm._loadEntryData([entryFor(FORS_ID, vm), entryFor(XRF_ID, vm)]);
        await flush();

        expect(vm.mixedConfigurations()).toBe(true);
        // Null storedConfig is what withdraws the view control: viewsFor(null)
        // offers the base quantity alone, so Kubelka-Munk cannot be applied to
        // the XRF counts sitting on the same chart.
        expect(vm.storedConfig()).toBeNull();
        expect(vm.showViewControl()).toBe(false);
    });

    it('says so rather than restating what the first configuration applied', async () => {
        await vm._loadEntryData([entryFor(FORS_ID, vm), entryFor(XRF_ID, vm)]);
        await flush();

        expect(vm.processingNote()).toBe(
            'These files use different configurations.'
        );
    });

    it('drops the Y axis label no single file answers for', async () => {
        await vm._loadEntryData([entryFor(FORS_ID, vm), entryFor(XRF_ID, vm)]);
        await flush();

        expect(vm.chartYAxisLabel()).toBe('Y Axis');
    });
});
