/**
 * Vitest unit spec: the project shadow of Arches' file-viewer card viewmodel.
 *
 * Covers the three behaviours the shadow adds (see its header): the renderer
 * component follows the renderer of the displayed file, the Loaders bar
 * accumulates compatibility over every staged file, and a staged tile with an
 * empty file list is skipped.
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

const XY_ID = 'e93b7b27-40d8-4141-996e-e59ff08742f3';
const PDF_ID = '09dec059-1ee8-4fbd-85dd-c0ab0428aa94';
const FILE_NODE_ID = 'b0000000-0000-4000-8000-000000000003';

vi.mock('arches', () => ({ default: { urls: {}, translations: {} } }));

vi.mock('file-renderers', () => ({
    default: {
        'e93b7b27-40d8-4141-996e-e59ff08742f3': {
            id: 'e93b7b27-40d8-4141-996e-e59ff08742f3',
            name: 'xy-reader',
            type: 'text/csv',
            ext: 'csv',
        },
        '09dec059-1ee8-4fbd-85dd-c0ab0428aa94': {
            id: '09dec059-1ee8-4fbd-85dd-c0ab0428aa94',
            name: 'pdfreader',
            type: 'application/pdf',
            ext: 'pdf',
        },
    },
}));

vi.mock('uuid', () => ({ default: { generate: () => 'uuid' } }));
vi.mock('dropzone', () => ({ default: {} }));

vi.mock('viewmodels/card-component', () => ({
    default: function CardComponentViewModel(params) {
        this.card = params.card;
    },
}));
vi.mock('viewmodels/card-multi-select', () => ({ default: function () {} }));
vi.mock('views/components/workbench', () => ({
    default: function WorkbenchComponentViewModel() {
        this.activeTab = ko.observable();
        this.toggleTab = vi.fn();
    },
}));

let FileViewerModel;
beforeAll(async () => {
    const realRegister = ko.components.register;
    ko.components.register = (name, config) => {
        FileViewerModel = config.viewModel;
    };
    await import('./file-viewer.js');
    ko.components.register = realRegister;
});

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const buildTile = (tileid, entries) => ({
    tileid,
    selected: ko.observable(false),
    save: vi.fn(),
    data: { [FILE_NODE_ID]: ko.observableArray(entries) },
});

const csv = (name = 'a.csv') => ({ name, type: 'text/csv', renderer: XY_ID });
const pdf = (name = 'b.pdf') => ({
    name,
    type: 'application/pdf',
    renderer: PDF_ID,
});

const buildViewModel = (tiles) => {
    const card = {
        nodegroupid: 'ng',
        tiles: ko.observableArray(tiles),
        staging: ko.observableArray([]),
        widgets: ko.observableArray([]),
        model: {
            nodes: ko.observableArray([
                {
                    datatype: () => 'file-list',
                    nodeGroupId: () => 'ng',
                    nodeid: FILE_NODE_ID,
                },
            ]),
        },
    };
    return new FileViewerModel({ card });
};

describe('file-viewer shadow', () => {
    let tiles;

    beforeEach(() => {
        tiles = [
            buildTile('t1', [csv()]),
            buildTile('t2', [pdf()]),
            buildTile('t3', [csv('c.csv')]),
        ];
    });

    it('mounts the renderer of the file on display, not the first one', async () => {
        const vm = buildViewModel(tiles);

        tiles[0].selected(true);
        await flush();
        expect(vm.rendererComponentName()).toBe('xy-reader');

        tiles[0].selected(false);
        tiles[1].selected(true);
        await flush();
        expect(vm.rendererComponentName()).toBe('pdfreader');
    });

    it('keeps the last component name when the displayed file has no known renderer', async () => {
        const vm = buildViewModel(tiles);
        tiles[0].selected(true);
        await flush();

        tiles[0].selected(false);
        tiles[1].data[FILE_NODE_ID]([{ name: 'x.bin', type: 'x/y' }]);
        tiles[1].selected(true);
        await flush();
        expect(vm.rendererComponentName()).toBe('xy-reader');
    });

    it('disables a renderer when any staged file is incompatible, not only the last', () => {
        const vm = buildViewModel(tiles);

        vm.card.staging(['t1', 't2', 't3']);

        const xy = vm.fileFormatRenderers.find((r) => r.id === XY_ID);
        expect(xy.disabled).toBe(true);
    });

    it('enables a renderer every staged file accepts', () => {
        tiles = [buildTile('t1', [csv()]), buildTile('t3', [csv('c.csv')])];
        const vm = buildViewModel(tiles);

        vm.card.staging(['t1', 't3']);

        const xy = vm.fileFormatRenderers.find((r) => r.id === XY_ID);
        expect(xy.disabled).toBe(false);
    });

    it('skips a staged tile whose file list is empty', () => {
        tiles = [buildTile('t1', [csv()]), buildTile('t4', [])];
        const vm = buildViewModel(tiles);

        expect(() => vm.card.staging(['t1', 't4'])).not.toThrow();
        expect(() => vm.applyRendererToStaged(null)).not.toThrow();
    });
});
