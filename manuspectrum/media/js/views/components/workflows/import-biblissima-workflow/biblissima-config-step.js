import ko from 'knockout';
import arches from 'arches';
import 'bindings/select2-query';
import ResourceInstanceSelectViewModel from 'viewmodels/resource-instance-select';
import biblissimaConfigStepTemplate from 'templates/views/components/workflows/import-biblissima-workflow/biblissima-config-step.htm';

const DOCUMENT_GRAPH_ID = '0c8226c1-11a9-4c48-9601-a7a0c6f2df6b';
const PROJECT_GRAPH_ID = '87a4319d-3ca5-43f6-88cc-a7379fba67f6';

// Default type value IDs (prefLabel valueid, not conceptid)
const VALUEID_MANUSCRIT = '30931466-b4e0-4527-ac93-b7290e80084c';
const VALUEID_DECOR = '3ff3726d-2a5a-450e-a558-105e065bb60f';

// RDM Collections
const RDM_DOC_TYPE = '73cf3108-5fef-429b-a92f-24074871aed9';
const RDM_COMP_TYPE = 'e85080b2-c39b-4e37-b6bc-b57d34092b7b';

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
    this.defaultType = ko.observable(null);

    // Computed
    this.isComponent = ko.computed(() => self.resourceType() === 'Component');
    this.currentRdmCollection = ko.observable(RDM_DOC_TYPE);

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
    this.parentDocPicker.value.subscribe((val) => {
        if (val && val.length > 0) {
            const item = val[0];
            self.parentDocumentId(item.resourceId || item.resourceinstanceid || item);
            self.parentDocumentName(item.displayname || item.resourceName?.() || '');
        } else {
            self.parentDocumentId(null);
            self.parentDocumentName('');
        }
    });

    this.projectPicker.value.subscribe((val) => {
        if (val && val.length > 0) {
            const item = val[0];
            self.projectId(item.resourceId || item.resourceinstanceid || item);
            self.projectName(item.displayname || item.resourceName?.() || '');
        } else {
            self.projectId(null);
            self.projectName('');
        }
    });

    // Reset parent document and update RDM collection when switching type
    this.resourceType.subscribe((type) => {
        if (type === 'Document') {
            self.parentDocumentId(null);
            self.parentDocumentName('');
            self.parentDocPicker.value([]);
            self.defaultType(VALUEID_MANUSCRIT);
            self.currentRdmCollection(RDM_DOC_TYPE);
        } else {
            self.defaultType(VALUEID_DECOR);
            self.currentRdmCollection(RDM_COMP_TYPE);
        }
    });

    // Set initial default type
    this.defaultType(VALUEID_MANUSCRIT);

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
            if (cached.defaultType) self.defaultType(cached.defaultType);
        }
    };

    this.submit = () => {
        const data = {
            resourceType: self.resourceType(),
            parentDocumentId: self.parentDocumentId(),
            parentDocumentName: self.parentDocumentName(),
            projectId: self.projectId(),
            projectName: self.projectName(),
            defaultType: self.defaultType(),
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
