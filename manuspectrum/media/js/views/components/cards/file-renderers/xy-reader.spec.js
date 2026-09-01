/**
 * Vitest unit spec — xy-reader.js chart display state.
 *
 * Arches builds a file renderer TWICE per displayed file: once for the chart
 * (`context: 'render'`) and once for the side panel that hosts the
 * configuration picker (`context: 'tab-contents'`). See
 * arches/app/templates/views/components/file-workbench.htm. The two instances
 * only ever talk through `params.state`, the single object Arches hangs off
 * each entry of `fileFormatRenderers`.
 *
 * So every chart setting a configuration drives has to live on that shared
 * state — otherwise picking a configuration in the panel updates the panel's
 * private copy and the chart keeps whatever it loaded with.
 *
 * Note: this file lives under media/js/views/components/, which coverage.include
 * does not target, so it executes without touching the coverage gate.
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

const RENDERER_ID = 'e1e0e1a7-2a1c-4b3f-9c4e-9f0d3c2b1a00';
const MALDI_ID = 'a0000000-0000-4000-8000-000000000001';
const FTIR_ID = 'a0000000-0000-4000-8000-000000000002';
const FILE_NODE_ID = 'b0000000-0000-4000-8000-000000000003';

vi.mock('arches', () => ({
    default: {
        translations: {
            data: 'Data',
            xAxis: 'X axis',
            yAxis: 'Y axis',
            xyVizTab: 'Viz',
        },
        urls: { renderer_config: '/renderer/config' },
    },
}));

vi.mock('utils/dispose', () => ({ default: vi.fn() }));

vi.mock('views/components/plugins/importer-configuration', () => ({
    default: {},
}));

// What the renderer endpoint hands back, mutable so a spec can stand in for a
// curator editing a configuration and saving it.
const stored = vi.hoisted(() => ({ configs: [] }));

const BASE_CONFIGS = [
    {
        configid: MALDI_ID,
        name: 'MALDI',
        config: {
            display: {
                chartTitle: 'MALDI',
                xAxisLabel: 'm/z',
                yAxisLabel: 'Intensity',
                xReversed: false,
            },
        },
    },
    {
        configid: FTIR_ID,
        name: 'FTIR',
        config: {
            display: {
                chartTitle: 'FTIR',
                xAxisLabel: 'Wavenumber (cm-1)',
                yAxisLabel: 'Absorbance',
                // FTIR runs 4000 -> 400 cm-1 by convention.
                xReversed: true,
            },
            transforms: [{ type: 'smooth' }],
        },
    },
];

vi.mock('utils/renderer-cache', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        invalidate: vi.fn(),
        getRendererConfig: vi.fn(async () => ({ configs: stored.configs })),
    };
});

// Stands in for viewmodels/afs-instrument, which webpack aliases and vitest
// stubs out. Only its state contract matters here: it hangs every chart
// observable off `params.state` so sibling instances share them, and it kicks
// off an AJAX render we do not want in a unit test.
vi.mock('viewmodels/afs-instrument', () => ({
    default: function AfsInstrumentViewModel(params) {
        this.params = params;
        this.loading = ko.observable(true);
        this.commonData = params.state;
        this.fileViewer = params.fileViewer;
        this.displayContent = ko.unwrap(params.displayContent);
        this.renderer = this.displayContent.renderer.id;

        if ('chartData' in params.state === false) {
            this.commonData.chartData = ko.observable();
            this.commonData.seriesData = ko.observableArray([]);
            this.commonData.seriesStyles = ko.observableArray([]);
        }
        if ('chartTitle' in params.state === false) {
            this.commonData.chartTitle = ko.observable('');
            this.commonData.titleSize = ko.observable(24);
            this.commonData.xAxisLabel = ko.observable('');
            this.commonData.xAxisLabelSize = ko.observable(17);
            this.commonData.yAxisLabel = ko.observable('');
            this.commonData.yAxisLabelSize = ko.observable(17);
            this.commonData.yAxisRightLabel = ko.observable('');
        }

        this.chartData = this.commonData.chartData;
        this.chartTitle = this.commonData.chartTitle;
        this.titleSize = this.commonData.titleSize;
        this.xAxisLabel = this.commonData.xAxisLabel;
        this.xAxisLabelSize = this.commonData.xAxisLabelSize;
        this.yAxisLabel = this.commonData.yAxisLabel;
        this.yAxisLabelSize = this.commonData.yAxisLabelSize;
        this.yAxisRightLabel = this.commonData.yAxisRightLabel;
        this.seriesData = this.commonData.seriesData;
        this.seriesStyles = this.commonData.seriesStyles;

        this.render = vi.fn();
    },
}));

// ko.components.register() returns nothing, so grab the viewmodel constructor
// on the way past.
let XyReaderViewModel;
beforeAll(async () => {
    const realRegister = ko.components.register;
    ko.components.register = (name, config) => {
        XyReaderViewModel = config.viewModel;
    };
    await import('./xy-reader.js');
    ko.components.register = realRegister;
});

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const buildFileViewer = (storedConfigId) => {
    const entry = {
        file_id: 'c0000000-0000-4000-8000-000000000004',
        name: 'spectrum.csv',
        url: '/files/spectrum.csv',
        renderer: RENDERER_ID,
        rendererConfig: storedConfigId,
        rendererConfigSource: 'auto',
    };
    const tile = {
        tileid: 'd0000000-0000-4000-8000-000000000005',
        data: { [FILE_NODE_ID]: ko.observableArray([entry]) },
        save: vi.fn(async () => {}),
    };
    const displayContent = ko.observable({
        name: 'spectrum.csv',
        url: '/files/spectrum.csv',
        file_id: entry.file_id,
        renderer: { id: RENDERER_ID },
        validRenderer: ko.observable(true),
        tile: tile,
    });
    return {
        entry,
        tile,
        fileViewer: {
            fileListNodeId: FILE_NODE_ID,
            displayContent: displayContent,
            activeTab: ko.observable('file-context'),
            tile: tile,
            card: {
                tiles: ko.observableArray([tile]),
                staging: ko.observableArray([]),
            },
        },
    };
};

describe('xy-reader chart display state', () => {
    let fixture;
    let chartVm;
    let panelVm;

    beforeEach(async () => {
        stored.configs = structuredClone(BASE_CONFIGS);
        fixture = buildFileViewer(MALDI_ID);
        // The one object Arches shares between the two renderer instances.
        const state = {};
        const params = (context) => ({
            fileViewer: fixture.fileViewer,
            card: fixture.fileViewer.card,
            selected: ko.observable(true),
            state: state,
            displayContent: fixture.fileViewer.displayContent,
            context: context,
        });
        chartVm = new XyReaderViewModel(params('render'));
        panelVm = new XyReaderViewModel(params('tab-contents'));
        await flush();
    });

    it('starts both instances on the configuration stored on the file', () => {
        expect(chartVm.selectedConfig()).toBe(MALDI_ID);
        expect(panelVm.selectedConfig()).toBe(MALDI_ID);
        expect(chartVm.xReversed()).toBe(false);
    });

    it('reverses the chart X axis when the side panel picks a reversed configuration', () => {
        panelVm.selectedConfig(FTIR_ID);

        // The chart is bound to the 'render' instance, so that is the copy the
        // plot reads — picking FTIR in the panel has to reach it.
        expect(chartVm.xReversed()).toBe(true);
    });

    it('restates the applied processing on the chart when the side panel changes configuration', () => {
        panelVm.selectedConfig(FTIR_ID);

        expect(chartVm.processing()).toBe(panelVm.processing());
        expect(chartVm.processing()).toBeTruthy();
    });

    it('keeps the axis labels in step, as they already were', () => {
        panelVm.selectedConfig(FTIR_ID);

        expect(chartVm.xAxisLabel()).toBe('Wavenumber (cm-1)');
        expect(chartVm.chartTitle()).toBe('FTIR');
    });

    it('reverses the chart X axis when the picked configuration is edited and saved', async () => {
        // The other way a curator turns the axis around: instead of picking a
        // different configuration, tick "reverse X" on the one already showing
        // and save. The panel calls back through onConfigSaved.
        stored.configs.find(
            (c) => c.configid === MALDI_ID
        ).config.display.xReversed = true;

        await panelVm.onConfigSaved();

        expect(chartVm.xReversed()).toBe(true);
    });

    it('derives the Y axis label from the applied chain on the save path too', async () => {
        const maldi = stored.configs.find((c) => c.configid === MALDI_ID);
        maldi.config.transforms = [{ type: 'normalize-max' }];

        await panelVm.onConfigSaved();

        // The stored string alone would read "Intensity" and quietly misstate
        // what the curve now shows.
        expect(chartVm.yAxisLabel()).toBe('Intensity [normalised to max]');
        expect(chartVm.processing()).toBe('normalize-max');
    });
});

describe('xy-reader parsing overrides', () => {
    let fixture;
    let vm;

    beforeEach(async () => {
        stored.configs = structuredClone(BASE_CONFIGS);
        fixture = buildFileViewer(MALDI_ID);
        // Arches' tile.save() runs koMapping.fromJS over tile.data, which
        // replaces the entry objects rather than mutating them. Reproduce that
        // here: anything held from before the save becomes an orphan.
        fixture.tile.save = vi.fn(async () => {
            const node = fixture.tile.data[FILE_NODE_ID];
            node(node().map((entry) => ({ ...entry })));
        });
        vm = new XyReaderViewModel({
            fileViewer: fixture.fileViewer,
            card: fixture.fileViewer.card,
            selected: ko.observable(true),
            state: {},
            displayContent: fixture.fileViewer.displayContent,
            context: 'tab-contents',
        });
        await flush();
    });

    const liveNode = () => fixture.tile.data[FILE_NODE_ID]();

    it('writes to the entry tile data holds, not to the captured copy', async () => {
        // The reproducible path: tick files in the Status tab, apply a
        // configuration to them (which saves), then open the override panel.
        // The selection still holds entries captured before that save.
        const captured = vm.allXyFiles()[0];
        await fixture.tile.save();

        vm.statusSelectedFiles([captured]);
        vm.showOverridePanel(true);
        vm.overrideDelimiterRadio('tab');

        await vm.saveOverrides();

        expect(liveNode()[0].parsingOverrides).toEqual({
            delimiterCharacter: '\t',
        });
        // The orphan is left untouched, which is where the write used to land.
        expect(captured.entry.parsingOverrides).toBeUndefined();
    });

    it('clears the selection and closes the panel once every file is written', async () => {
        vm.statusSelectedFiles([vm.allXyFiles()[0]]);
        vm.showOverridePanel(true);
        vm.overrideDelimiterRadio('tab');

        await vm.saveOverrides();

        expect(vm.showOverridePanel()).toBe(false);
        expect(vm.statusSelectedFiles()).toHaveLength(0);
    });

    it('keeps a file that could not be written ticked, and the panel open', async () => {
        // A cleared selection is how this reports success, so a failure must
        // not clear it.
        fixture.tile.save = vi.fn(async () => {
            throw new Error('tile refused');
        });
        vm.statusSelectedFiles([vm.allXyFiles()[0]]);
        vm.showOverridePanel(true);
        vm.overrideDelimiterRadio('tab');

        await vm.saveOverrides();

        expect(vm.showOverridePanel()).toBe(true);
        expect(vm.statusSelectedFiles()).toHaveLength(1);
    });
});
