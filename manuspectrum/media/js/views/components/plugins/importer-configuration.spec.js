/**
 * Vitest unit spec — importer-configuration.js loading and saving.
 *
 * `referenceColumnDeclared` guards the reference-normalise choice: untagging the
 * reference column downgrades it to "separate", because the normalisation has
 * nothing to divide by. The guard must fire on a curator's edit and stay out of
 * the way while a stored configuration is being loaded into the panel.
 *
 * The save path has its own rule: a refusal must reach the curator, and must not
 * close the panel over the edit that was refused.
 *
 * Note: this file lives under media/js/views/components/, which coverage.include
 * does not target, so it executes without touching the coverage gate.
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

vi.mock('arches', () => ({
    default: {
        translations: {
            configurationProtected: 'Protected configuration',
            configurationNotSaved: 'Configuration not saved',
            configurationNotSavedWarning: 'The server refused the change.',
        },
        urls: { renderer_config: '/renderer/config' },
    },
}));

// The vitest config stubs viewmodels/ to `{}`, which is not constructible.
vi.mock('viewmodels/alert', () => ({
    default: function AlertViewModel(type, title, text) {
        this.title = title;
        this.text = text;
    },
}));

// Bootstrap 3 reads a global jQuery at import time, which jsdom has not set up.
vi.mock('bootstrap', () => ({}));

vi.mock('utils/renderer-cache', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        invalidate: vi.fn(),
        getRendererConfig: vi.fn(async () => ({ configs: [] })),
    };
});

// ko.components.register() returns nothing, so grab the viewmodel constructor
// on the way past.
let ImporterConfigurationViewModel;
beforeAll(async () => {
    const realRegister = ko.components.register;
    ko.components.register = (name, config) => {
        ImporterConfigurationViewModel = config.viewModel;
    };
    await import('./importer-configuration.js');
    ko.components.register = realRegister;
});

const configWithReference = {
    configid: 'b0000000-0000-4000-8000-000000000001',
    name: "A lab's own FORS",
    description: 'target and white reference in separate columns',
    config: {
        multiYHandling: 'reference-normalize',
        display: {
            columnAssignments: [
                { columnIndex: 0, role: 'x' },
                { columnIndex: 1, role: 'yLeft' },
                { columnIndex: 2, role: 'reference' },
            ],
        },
    },
};

// The shape every seeded preset had before the column roles were added to the
// table: a normalisation declared with no column carrying the reference role.
const configWithoutAssignments = {
    configid: 'b0000000-0000-4000-8000-000000000002',
    name: 'FORS',
    description: 'wavelength / reflectance',
    config: {
        multiYHandling: 'reference-normalize',
        display: {},
    },
};

describe('loadConfiguration', () => {
    let vm;

    beforeEach(() => {
        vm = new ImporterConfigurationViewModel({
            rendererConfigs: ko.observableArray([]),
        });
    });

    it('keeps the reference-normalise choice a configuration stored', () => {
        vm.loadConfiguration(configWithReference);

        expect(vm.multiYHandling()).toBe('reference-normalize');
        expect(vm.referenceColumnDeclared()).toBe(true);
    });

    it('shows what the next configuration stored, not what the last one left', () => {
        vm.loadConfiguration(configWithReference);
        vm.loadConfiguration(configWithoutAssignments);

        // Clearing the column list flips referenceColumnDeclared true -> false
        // and wakes the guard. Loading the stored choice afterwards is what
        // keeps the panel showing the configuration rather than the guard's
        // reaction to the previous one — a single Save would otherwise write
        // that downgrade to the shared baseline.
        expect(vm.multiYHandling()).toBe('reference-normalize');
    });

    it('still downgrades when a curator untags the reference column', () => {
        vm.loadConfiguration(configWithReference);

        vm.columnAssignments()[2].role('yLeft');

        expect(vm.referenceColumnDeclared()).toBe(false);
        expect(vm.multiYHandling()).toBe('separate');
    });
});

describe('saveConfigEdit', () => {
    let vm;
    let alerts;

    const buildVm = () => {
        alerts = [];
        return new ImporterConfigurationViewModel({
            rendererConfigs: ko.observableArray([]),
            alert: (viewModel) => alerts.push(viewModel),
        });
    };

    const respondWith = (status, body) => {
        window.fetch = vi.fn(async () => ({
            ok: status >= 200 && status < 300,
            status,
            json: async () => {
                if (body === undefined) throw new Error('no body');
                return body;
            },
        }));
    };

    beforeEach(() => {
        vm = buildVm();
        vm.configurationName('A configuration');
        vm.showConfigurationPanel(true);
        vm.showImporterList(false);
    });

    it('closes the panel once the server has accepted the change', async () => {
        respondWith(200, { configid: 'x' });

        await vm.saveConfigEdit();

        expect(vm.showConfigurationPanel()).toBe(false);
        expect(vm.showImporterList()).toBe(true);
        expect(alerts).toHaveLength(0);
    });

    it('keeps the panel open and names the reason on a protected refusal', async () => {
        // A seeded preset edited by a non-superuser. The panel used to close on
        // this exactly as it does on success, so a curator saw their edit vanish
        // and had no way to tell it had been rejected.
        respondWith(403, {
            saved: false,
            reason: 'protected',
            message: 'This configuration is part of the shared baseline.',
        });

        await vm.saveConfigEdit();

        expect(vm.showConfigurationPanel()).toBe(true);
        expect(alerts).toHaveLength(1);
        expect(alerts[0].title).toBe('Protected configuration');
        expect(alerts[0].text).toBe(
            'This configuration is part of the shared baseline.'
        );
    });

    it('still reports a failure that carries no body', async () => {
        // A 500 from RendererConfig.DoesNotExist has no JSON to read.
        respondWith(500, undefined);

        await vm.saveConfigEdit();

        expect(vm.showConfigurationPanel()).toBe(true);
        expect(alerts).toHaveLength(1);
        expect(alerts[0].title).toBe('Configuration not saved');
        expect(alerts[0].text).toBe('The server refused the change.');
    });
});

describe('startNewConfiguration', () => {
    let vm;

    beforeEach(() => {
        vm = new ImporterConfigurationViewModel({
            rendererConfigs: ko.observableArray([]),
        });
    });

    it('carries nothing over from the configuration last edited', () => {
        vm.loadConfiguration({
            ...configWithReference,
            config: {
                ...configWithReference.config,
                delimiterCharacter: '|',
                display: {
                    ...configWithReference.config.display,
                    chartTitle: 'A lab chart',
                    xAxisLabel: 'Wavelength (nm)',
                },
            },
        });

        vm.startNewConfiguration();

        expect(vm.editConfigurationId()).toBeUndefined();
        expect(vm.configurationName()).toBeUndefined();
        expect(vm.chartTitle()).toBeUndefined();
        expect(vm.xAxisLabel()).toBeUndefined();
        expect(vm.dataDelimiter()).toBeUndefined();
        expect(vm.columnAssignments()).toHaveLength(0);
        expect(vm.multiYHandling()).toBe('separate');
    });

    it('opens the panel on the list it replaces', () => {
        vm.startNewConfiguration();

        expect(vm.showConfigurationPanel()).toBe(true);
        expect(vm.showImporterList()).toBe(false);
    });

    it('releases a delimiter that had disabled saving', () => {
        // The case that made a configuration uneditable for good: a stored
        // delimiter that is not a valid expression raises invalidDelimiter,
        // which disables Save — and the field that could repair it was gone.
        vm.loadConfiguration({
            ...configWithReference,
            config: { ...configWithReference.config, delimiterCharacter: '[a' },
        });
        expect(vm.invalidDelimiter()).toBe(true);

        vm.startNewConfiguration();

        expect(vm.invalidDelimiter()).toBe(false);
    });
});
