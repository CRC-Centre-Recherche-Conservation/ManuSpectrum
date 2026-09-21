/**
 * Shadow of arches_controlled_lists/media/js/views/components/plugins/controlled-list-manager.js
 * (arches_controlled_lists 1.2.0).
 *
 * Diff vs original:
 *   - the Knockout viewModel keeps the Vue application handle (`vueApp`),
 *     unmounts it in `dispose()`, and skips mounting when the component was
 *     disposed before `createVueApplication` resolved
 *   - preset, theme, router and template are unchanged
 */

import ko from 'knockout';

import { definePreset, palette } from '@primeuix/themes';
import { ArchesPreset, DEFAULT_THEME } from '@/arches/themes/default.ts';
import { routes } from '@/arches_controlled_lists/routes.ts';
import ControlledListManager from '@/arches_controlled_lists/plugins/ControlledListManager.vue';
import { createVueApplication } from '@/arches_vue_components/application';
import ControlledListManagerTemplate from 'templates/views/components/plugins/controlled-list-manager.htm';

import { createRouter, createWebHistory } from 'vue-router';

const router = createRouter({
    history: createWebHistory(),
    routes,
});

const ControlledListsPreset = definePreset(ArchesPreset, {
    semantic: {
        iconSize: '1.2rem',
        colorScheme: {
            light: {
                primary: palette(ArchesPreset.primitive.arches.blue),
                dialog: {
                    headerTextColor: "{slate.50}",
                },  
            },
            dark: {
                dialog: {
                    headerTextColor: "{slate.50}",
                },
            },
        },
    },
    components: {
        button: {
            colorScheme: {
                light: {
                    primary: {
                        background: "{primary-800}",
                        borderColor: "{button-primary-background}",
                    },
                    danger: {
                        background: "{orange-700}",
                        borderColor: "{orange-700}",
                        hover: {
                            background: "{orange-500}",
                            borderColor: "{orange-500}",
                        },
                    },
                },
            },
            root: {
                label: {
                    fontWeight: 600,
                },
            },
            border: {
                radius: '.25rem',
            },
        },
        toast: {
            summary: { fontSize: '1.5rem' },
            detail: { fontSize: '1.25rem' },
        },
    },
});

const ControlledListsTheme = {
    theme: {
        ...DEFAULT_THEME.theme,
        preset: ControlledListsPreset,
    },
};

/**
 * Knockout host of the Vue Controlled List Manager.
 *
 * The Vue application is created asynchronously; the handle is kept so
 * teardown can unmount it, and a host disposed before creation finished
 * never mounts.
 */
const viewModel = function() {
    const self = this;
    this.vueApp = null;
    this.disposed = false;

    createVueApplication({ component: ControlledListManager, themeConfiguration: ControlledListsTheme }).then((vueApp) => {
        if (self.disposed) {
            return;
        }
        vueApp.use(router);
        vueApp.mount('#controlled-list-manager-mounting-point');
        self.vueApp = vueApp;
    });

    this.dispose = function() {
        self.disposed = true;
        if (self.vueApp) {
            self.vueApp.unmount();
            self.vueApp = null;
        }
    };
};

ko.components.register('controlled-list-manager', {
    viewModel: viewModel,
    template: ControlledListManagerTemplate,
});
