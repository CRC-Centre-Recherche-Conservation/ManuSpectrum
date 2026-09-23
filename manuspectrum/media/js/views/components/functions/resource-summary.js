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
 * After a removal the page is reloaded through its own `navigate()`, so pending
 * edits of other functions are confirmed first (the removal has already
 * happened by then). The URL drops the hash: the function manager's `href="#"`
 * links can leave one, and a change of hash alone would not reload the page.
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
        this.mountingPointId = 'summary-config-' + this.graphid;
        this.vueApp = null;
        this.disposed = false;

        createVueApplication({
            component: SummaryConfigForm,
            initialProps: {
                graphid: self.graphid,
                onDetached: function() {
                    const mountingPoint = document.getElementById(self.mountingPointId);
                    const page = mountingPoint && ko.contextFor(mountingPoint);
                    if (page && page.$root && typeof page.$root.navigate === 'function') {
                        page.$root.navigate(window.location.pathname + window.location.search);
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
