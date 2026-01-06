// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science

import ko from 'knockout';
import $ from 'jquery';
import arches from 'arches';
import Workflow from 'viewmodels/workflow';
import AlertViewModel from 'viewmodels/alert';
import createProjectWorkflowTemplate from 'templates/views/components/plugins/create-project-workflow.htm';
import 'viewmodels/workflow-step';
import 'views/components/workflows/create-project-workflow/project-name-step';
import 'views/components/workflows/create-project-workflow/add-things-step';
import 'views/components/workflows/create-project-workflow/create-project-final-step';

const viewModel = function(params) {
    this.componentName = 'create-project-workflow';

    this.stepConfig = [
        {
            title: arches.translations.projectName,
            name: 'set-project-name',
            required: true,
            layoutSections: [
                {
                    componentConfigs: [
                        {
                            componentName: 'project-name-step',
                            uniqueInstanceName: 'project-name',
                            parameters: {},
                        },
                    ],
                },
            ]
        },
        {
            title: arches.translations.projectStatement,
            name: 'set-project-statement',
            required: false,
            layoutSections: [
                {
                    componentConfigs: [
                        {
                            componentName: 'default-card',
                            uniqueInstanceName: 'project-statement',
                            tilesManaged: 'one',
                            parameters: {
                                graphid: '87a4319d-3ca5-43f6-88cc-a7379fba67f6',
                                nodegroupid: 'e18cc401-7020-11ef-8753-0575b5bada34',
                                resourceid: "['set-project-name']['project-name']['projectResourceId']",
                                hiddenNodes: ['e18cc408-7020-11ef-8753-0575b5bada34']
                            },
                        },
                    ],
                },
            ],
        },
        {
            title: arches.translations.projectStart,
            name: 'set-project-timespan',
            required: false,
            layoutSections: [
                {
                    componentConfigs: [
                        {
                            componentName: 'default-card',
                            uniqueInstanceName: 'project-timespan',
                            tilesManaged: 'one',
                            parameters: {
                                graphid: '87a4319d-3ca5-43f6-88cc-a7379fba67f6',
                                nodegroupid: 'e77c870f-7022-11ef-8753-0575b5bada34',
                                resourceid: "['set-project-name']['project-name']['projectResourceId']",
                            },
                        },
                    ],
                },
            ],
        },
        {
            title: arches.translations.projectTeam,
            name: 'set-project-team',
            required: false,
            layoutSections: [
                {
                    componentConfigs: [
                        {
                            componentName: 'default-card',
                            uniqueInstanceName: 'project-team',
                            tilesManaged: 'one',
                            parameters: {
                                graphid: '87a4319d-3ca5-43f6-88cc-a7379fba67f6',
                                nodegroupid: '95385f5e-7022-11ef-8753-0575b5bada34',
                                resourceid: "['set-project-name']['project-name']['projectResourceId']",
                            },
                        },
                    ],
                },
            ],
        },
        {
            title: arches.translations.addObjects,
            name: 'object-search-step',
            required: true,
            workflowstepclass: 'create-project-add-things-step',
            layoutSections: [
                {
                    componentConfigs: [
                        {
                            componentName: 'add-things-step',
                            uniqueInstanceName: 'add-documents',
                            tilesManaged: 'one',
                            parameters: {
                                graphid: '87a4319d-3ca5-43f6-88cc-a7379fba67f6',
                                nodegroupid: 'a8fb3c9e-bbc4-11ef-bd5f-ed806b645d76',
                                nodeid: 'a8fb3c9e-bbc4-11ef-bd5f-ed806b645d76',
                                documentGraphId: '0c8226c1-11a9-4c48-9601-a7a0c6f2df6b',
                                resourceid: "['set-project-name']['project-name']['projectResourceId']",
                                projectStepData: "['set-project-name']['project-name']"
                            },
                        },
                    ],
                },
            ],
        },
        {
            title: arches.translations.summary,
            name: 'add-project-complete',
            description: arches.translations.summary,
            layoutSections: [
                {
                    componentConfigs: [
                        {
                            componentName: 'create-project-final-step',
                            uniqueInstanceName: 'create-project-final',
                            tilesManaged: 'none',
                            parameters: {
                                resourceid: "['set-project-name']['project-name']['projectResourceId']",
                                documentGraphId: '0c8226c1-11a9-4c48-9601-a7a0c6f2df6b',
                            },
                        },
                    ],
                },
            ],
        }
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

ko.components.register('create-project-workflow', {
    viewModel: viewModel,
    template: createProjectWorkflowTemplate
});

export default viewModel;
