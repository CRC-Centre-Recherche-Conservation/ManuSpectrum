/**
 * Import Biblissima workflow — step 1 (Configuration).
 *
 * Pick the resource type (Document or Component) and an optional Project
 * to link the imports to. The chosen resourceType is fixed for the rest
 * of the session: steps 2 and 3 branch on it and don't support
 * mid-workflow mode switching.
 *
 * Output: ``params.value({ resourceType, projectId, projectName })``
 * consumed by subsequent steps via ``configStepData``.
 *
 * Uses Arches' ``ResourceInstanceSelectViewModel`` for the Project picker
 * so that the user can also create a new resource inline (the
 * resource-creator panel is wired to ``activeNewResourceInstance``).
 */
import ko from 'knockout';
// Side-effect import: arches.js triggers utils/set-csrf-token, which wires the
// CSRF token into jQuery's ajaxSetup so the ResourceInstanceSelectViewModel
// pickers below can POST safely. Imported even though no `arches.*` symbol is
// referenced in this file — sister steps already pull it in, so the side
// effect runs once on first evaluation, but keep the explicit import here so
// step 1 stays robust to bundle-load ordering changes.
import 'arches';
import 'bindings/select2-query';
import ResourceInstanceSelectViewModel from 'viewmodels/resource-instance-select';
import biblissimaConfigStepTemplate from 'templates/views/components/workflows/import-biblissima-workflow/biblissima-config-step.htm';

const PROJECT_GRAPH_ID = '87a4319d-3ca5-43f6-88cc-a7379fba67f6';

/**
 * Create a resource picker using Arches' ResourceInstanceSelectViewModel.
 * Returns an object with select2Config ready to use in template.
 */
const createResourcePicker = (graphIds, allowCreate) => {
    const picker = {};
    const pickerParams = {
        graphids: graphIds,
        value: ko.observableArray([]),
        allowInstanceCreation: allowCreate,
        displayOntologyTable: false,
        renderContext: 'workflow',
        multiple: false,
        onlyManageResourceIds: true,
        disabled: ko.observable(false),
    };
    ResourceInstanceSelectViewModel.apply(picker, [pickerParams]);
    return picker;
};

const viewModel = function(params) {
    const self = this;

    this.resourceType = ko.observable('Document');
    this.projectId = ko.observable(null);
    this.projectName = ko.observable('');

    // Computed
    this.isComponent = ko.computed(() => self.resourceType() === 'Component');

    // Resource pickers using Arches' native VM
    this.projectPicker = createResourcePicker([PROJECT_GRAPH_ID], true);

    // Shared graphLookup for the creator panel template
    this.graphLookup = {};
    Object.assign(this.graphLookup, this.projectPicker.graphLookup);

    // Track which picker triggered creation (for sharing #resource-creator-panel)
    this.activeNewResourceInstance = ko.computed(
        () => self.projectPicker.newResourceInstance?.() || null,
    );

    // Sync picker values to our observables
    // With onlyManageResourceIds=true, value is a UUID string (not an object)
    this.projectPicker.value.subscribe((val) => {
        if (val && typeof val === 'string' && val.length > 10) {
            self.projectId(val);
            const selected = self.projectPicker.selectedItem?.();
            self.projectName(selected?._source?.displayname || val);
        } else {
            self.projectId(null);
            self.projectName('');
        }
    });

    // Validation
    this.canProceed = ko.computed(() => true);

    // Restore from cached value
    this.initialize = () => {
        if (params.value()) {
            const cached = ko.unwrap(params.value);
            if (cached.resourceType) self.resourceType(cached.resourceType);
            if (cached.projectId) self.projectId(cached.projectId);
            if (cached.projectName) self.projectName(cached.projectName);
        }
    };

    this.submit = () => {
        const data = {
            resourceType: self.resourceType(),
            projectId: self.projectId(),
            projectName: self.projectName(),
        };
        params.value(data);
        self.complete(true);
    };

    // Workflow step interface
    this.complete = params.form?.complete || ko.observable(false);
    this.savedData = params.form?.savedData || ko.observable({});

    this.initialize();
};

ko.components.register('biblissima-config-step', {
    viewModel: viewModel,
    template: biblissimaConfigStepTemplate,
});

export default viewModel;
