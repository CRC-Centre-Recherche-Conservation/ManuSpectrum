/**
 * Import Biblissima workflow — step 1 (Configuration).
 *
 * Pick the resource type (Document or Component), the parent Document if
 * creating a Component, and an optional Project to link the imports to.
 * The chosen resourceType is fixed for the rest of the session: steps 2
 * and 3 branch on it and don't support mid-workflow mode switching.
 *
 * Output: ``params.value({ resourceType, parentDocumentId, projectId, … })``
 * consumed by subsequent steps via ``configStepData``.
 *
 * Uses Arches' ``ResourceInstanceSelectViewModel`` for the parent Document
 * and Project pickers so that the user can also create a new resource
 * inline (the resource-creator panel shares its slot between both pickers
 * via ``activeNewResourceInstance``).
 */
import ko from 'knockout';
import arches from 'arches';
import 'bindings/select2-query';
import ResourceInstanceSelectViewModel from 'viewmodels/resource-instance-select';
import biblissimaConfigStepTemplate from 'templates/views/components/workflows/import-biblissima-workflow/biblissima-config-step.htm';

const DOCUMENT_GRAPH_ID = '0c8226c1-11a9-4c48-9601-a7a0c6f2df6b';
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
    this.parentDocumentId = ko.observable(null);
    this.parentDocumentName = ko.observable('');
    this.projectId = ko.observable(null);
    this.projectName = ko.observable('');

    // Computed
    this.isComponent = ko.computed(() => self.resourceType() === 'Component');

    // Resource pickers using Arches' native VM
    this.parentDocPicker = createResourcePicker([DOCUMENT_GRAPH_ID], true);
    this.projectPicker = createResourcePicker([PROJECT_GRAPH_ID], true);

    // Shared graphLookup for the creator panel template
    this.graphLookup = {};
    Object.assign(this.graphLookup, this.parentDocPicker.graphLookup);
    Object.assign(this.graphLookup, this.projectPicker.graphLookup);

    // Track which picker triggered creation (for sharing #resource-creator-panel)
    this.activeNewResourceInstance = ko.computed(() =>
        self.projectPicker.newResourceInstance?.() ||
        self.parentDocPicker.newResourceInstance?.() ||
        null
    );

    // Sync picker values to our observables
    // With onlyManageResourceIds=true, value is a UUID string (not an object)
    this.parentDocPicker.value.subscribe((val) => {
        if (val && typeof val === 'string' && val.length > 10) {
            self.parentDocumentId(val);
            // Get name from selectedItem
            const selected = self.parentDocPicker.selectedItem?.();
            self.parentDocumentName(selected?._source?.displayname || val);
        } else {
            self.parentDocumentId(null);
            self.parentDocumentName('');
        }
    });

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

    // Reset parent document when switching back to Document type
    this.resourceType.subscribe((type) => {
        if (type === 'Document') {
            self.parentDocumentId(null);
            self.parentDocumentName('');
            self.parentDocPicker.value([]);
        }
    });

    // Validation
    this.canProceed = ko.computed(() => {
        if (self.isComponent() && !self.parentDocumentId()) {
            return false;
        }
        return true;
    });

    // Restore from cached value
    this.initialize = () => {
        if (params.value()) {
            const cached = ko.unwrap(params.value);
            if (cached.resourceType) self.resourceType(cached.resourceType);
            if (cached.parentDocumentId) self.parentDocumentId(cached.parentDocumentId);
            if (cached.parentDocumentName) self.parentDocumentName(cached.parentDocumentName);
            if (cached.projectId) self.projectId(cached.projectId);
            if (cached.projectName) self.projectName(cached.projectName);
        }
    };

    this.submit = () => {
        const data = {
            resourceType: self.resourceType(),
            parentDocumentId: self.parentDocumentId(),
            parentDocumentName: self.parentDocumentName(),
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
