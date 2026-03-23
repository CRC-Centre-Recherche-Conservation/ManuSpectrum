import ko from 'knockout';
import arches from 'arches';
import importBiblissimaFinalStepTemplate from 'templates/views/components/workflows/import-biblissima-workflow/import-biblissima-final-step.htm';

const viewModel = function(params) {
    const self = this;

    this.loading = ko.observable(false);
    this.complete = params.form?.complete || ko.observable(true);

    // Data from previous steps
    this.createData = params.createStepData || {};
    this.configData = params.configStepData || {};

    this.createdResources = ko.observableArray(this.createData.createdResources || []);
    this.skippedCount = ko.observable(this.createData.skippedCount || 0);
    this.errorCount = ko.observable(this.createData.errorCount || 0);
    this.resourceType = this.createData.resourceType || 'Document';
    this.projectId = this.createData.projectId || null;
    this.projectName = this.configData.projectName || '';

    this.createdCount = ko.computed(() => self.createdResources().length);

    this.resourceUrl = (resourceId) => `/resource/${resourceId}`;
    this.projectUrl = ko.computed(() =>
        self.projectId ? `/resource/${self.projectId}` : null
    );
};

ko.components.register('import-biblissima-final-step', {
    viewModel: viewModel,
    template: importBiblissimaFinalStepTemplate,
});

export default viewModel;
