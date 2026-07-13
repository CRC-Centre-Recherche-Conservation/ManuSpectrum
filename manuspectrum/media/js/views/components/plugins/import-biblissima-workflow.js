import ko from 'knockout';
import $ from 'jquery';
import arches from 'arches';
import Workflow from 'viewmodels/workflow';
import AlertViewModel from 'viewmodels/alert';
import importBiblissimaWorkflowTemplate from 'templates/views/components/plugins/import-biblissima-workflow.htm';
import 'viewmodels/workflow-step';
import 'views/components/workflows/import-biblissima-workflow/biblissima-config-step';
import 'views/components/workflows/import-biblissima-workflow/biblissima-search-step';
import 'views/components/workflows/import-biblissima-workflow/biblissima-create-step';
import 'views/components/workflows/import-biblissima-workflow/import-biblissima-final-step';

const COMPONENT_GRAPH_ID = 'd47595b4-f8a6-419c-8f33-b388206280c4';

const viewModel = function(params) {
    this.componentName = 'import-biblissima-workflow';

    this.stepConfig = [
        {
            title: arches.translations.biblissimaConfig || 'Configuration',
            name: 'biblissima-config',
            required: true,
            layoutSections: [
                {
                    componentConfigs: [
                        {
                            componentName: 'biblissima-config-step',
                            uniqueInstanceName: 'config',
                            tilesManaged: 'none',
                            parameters: {
                                componentGraphId: COMPONENT_GRAPH_ID,
                            },
                        },
                    ],
                },
            ],
        },
        {
            title: arches.translations.biblissimaSearch || 'Recherche Biblissima',
            name: 'biblissima-search',
            required: true,
            workflowstepclass: 'biblissima-search-step-wrapper',
            layoutSections: [
                {
                    componentConfigs: [
                        {
                            componentName: 'biblissima-search-step',
                            uniqueInstanceName: 'search',
                            tilesManaged: 'none',
                            parameters: {
                                configStepData: "['biblissima-config']['config']",
                            },
                        },
                    ],
                },
            ],
        },
        {
            title: arches.translations.biblissimaCreate || 'Création & Validation',
            name: 'biblissima-create',
            required: true,
            workflowstepclass: 'biblissima-create-step-wrapper',
            layoutSections: [
                {
                    componentConfigs: [
                        {
                            componentName: 'biblissima-create-step',
                            uniqueInstanceName: 'create',
                            tilesManaged: 'none',
                            parameters: {
                                configStepData: "['biblissima-config']['config']",
                                searchStepData: "['biblissima-search']['search']",
                            },
                        },
                    ],
                },
            ],
        },
        {
            title: arches.translations.summary || 'Summary',
            name: 'biblissima-summary',
            description: arches.translations.summary || 'Summary',
            layoutSections: [
                {
                    componentConfigs: [
                        {
                            componentName: 'import-biblissima-final-step',
                            uniqueInstanceName: 'summary',
                            tilesManaged: 'none',
                            parameters: {
                                createStepData: "['biblissima-create']['create']",
                                configStepData: "['biblissima-config']['config']",
                            },
                        },
                    ],
                },
            ],
        },
    ];

    Workflow.apply(this, [params]);

    this.reverseWorkflowTransactions = () => {
        const quitUrl = this.quitUrl;
        return $.ajax({
            type: "POST",
            url: arches.urls.transaction_reverse(this.id())
        }).then(() => {
            params.loading(false);
            window.location.href = quitUrl;
        });
    };

    this.quitWorkflow = () => {
        this.alert(
            new AlertViewModel(
                'ep-alert-red',
                arches.translations.deleteWorkflowTitle,
                arches.translations.deleteWorkflowWarning,
                () => {},
                () => {
                    params.loading(arches.translations.cleaningUp);
                    this.reverseWorkflowTransactions();
                },
            )
        );
    };

    this.quitUrl = arches.urls.plugin('init-workflow');
};

ko.components.register('import-biblissima-workflow', {
    viewModel: viewModel,
    template: importBiblissimaWorkflowTemplate,
});

export default viewModel;
