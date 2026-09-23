import ko from 'knockout';
import FunctionViewModel from 'viewmodels/function-view-model';
import { createVueApplication } from '@/arches_vue_components/application';
import SummaryConfigForm from '@/manuspectrum/functions/SummaryConfigForm/SummaryConfigForm.vue';
import resourceSummaryTemplate from 'templates/views/components/functions/resource-summary.htm';

/**
 * Knockout shell around the Vue configuration form of the summary function.
 *
 * Nothing crosses from Knockout into Vue but the graph id and the `detached`
 * callback, passed as bootstrap props: the form reads, writes and removes its
 * configuration through its own endpoint, and the Save button of the function
 * manager plays no part.
 *
 * After a removal the entry leaves the function manager's list at once, as the
 * core delete handler does, and the page is then reloaded through its own
 * `navigate()`, so pending edits of other functions are confirmed first (the
 * removal has already happened by then). The URL drops the hash: the function
 * manager's `href="#"` links can leave one, and a change of hash alone would
 * not reload the page.
 *
 * The function manager destroys and rebuilds this component every time another
 * function is selected, so the Vue application is unmounted in `dispose()`,
 * and a teardown that happens while `createVueApplication` is still resolving
 * cancels the mount.
 */
export default ko.components.register('views/components/functions/resource-summary', {
    viewModel: function() {
        FunctionViewModel.apply(this, arguments);

        const self = this;
        // The applied-function model the Function Manager lists this shell under.
        const applied = arguments[0];
        this.mountingPointId = 'summary-config-' + this.graphid;
        this.vueApp = null;
        this.disposed = false;

        createVueApplication({
            component: SummaryConfigForm,
            initialProps: {
                graphid: self.graphid,
                /**
                 * The row is gone on the server: the Function Manager's list
                 * must forget it before anything else, as the core delete
                 * handler does (function-manager.js), since its Save re-sends
                 * every listed function and its trash icon fetches the row.
                 * The reload then goes through the page's `navigate()`, which
                 * asks first when other functions hold unsaved edits.
                 */
                onDetached: function() {
                    const mountingPoint = document.getElementById(self.mountingPointId);
                    const page = mountingPoint && ko.contextFor(mountingPoint);
                    const root = page && page.$root;
                    const list = root && root.appliedFunctionList;
                    if (list && typeof list.items === 'function') {
                        list.items.remove(applied);
                        if (typeof root.toggleFunctionLibrary === 'function') {
                            root.toggleFunctionLibrary();
                        }
                    }
                    if (root && typeof root.navigate === 'function') {
                        root.navigate(window.location.pathname + window.location.search);
                    } else {
                        window.location.reload();
                    }
                },
            },
        }).then(function(vueApp) {
            const mountingPoint = document.getElementById(self.mountingPointId);
            if (self.disposed || !mountingPoint) {
                return;
            }
            self.vueApp = vueApp;
            vueApp.mount(mountingPoint);
        }).catch(function(error) {
            console.error('The summary configuration form could not start', error);
        });

        this.dispose = function() {
            self.disposed = true;
            if (self.vueApp) {
                self.vueApp.unmount();
                self.vueApp = null;
            }
        };
    },
    template: resourceSummaryTemplate,
});
