/**
 * Vitest unit spec — importer-configuration.js configuration loading.
 *
 * `referenceColumnDeclared` guards the reference-normalise choice: untagging the
 * reference column downgrades it to "separate", because the normalisation has
 * nothing to divide by. The guard must fire on a curator's edit and stay out of
 * the way while a stored configuration is being loaded into the panel.
 *
 * Note: this file lives under media/js/views/components/, which coverage.include
 * does not target, so it executes without touching the coverage gate.
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

vi.mock('arches', () => ({
    default: {
        translations: {},
        urls: { renderer_config: '/renderer/config' },
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
