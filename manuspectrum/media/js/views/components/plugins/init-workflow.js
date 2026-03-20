// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science

import ko from 'knockout';
import arches from 'arches';
import JsonErrorAlertViewModel from 'viewmodels/alert-json';
import initWorkflowTemplate from 'templates/views/components/plugins/init-workflow.htm';

const InitWorkflow = function(params) {
    this.workflows = ko.observableArray([]);
    this.helpTemplateData = ko.observableArray([]);

    // Collapsible groups - open by default
    this.showProjectsGroup = ko.observable(true);

    fetch(arches.urls.api_plugins).then((resp) => {
        if (resp.ok) {
            return resp.json();
        } else {
            params.alert(new JsonErrorAlertViewModel('ep-alert-red', resp.responseJSON));
        }
    }).then((respJSON) => {
        const workflows = respJSON.reduce((acc, plugin) => {
            if (plugin.config.is_workflow) {
                plugin.url = arches.urls.plugin(plugin.slug);
                acc.push(plugin);
            }
            return acc;
        }, []);

        this.workflows(workflows);
        this.helpTemplateData(workflows.reduce((acc, workflow) => {
            if (workflow.helptemplate) {
                acc.push({ text: workflow.name, id: workflow.helptemplate });
            }
            return acc;
        }, []));
    });

    this.shouldShowWorkflowHelp = ko.observable(false);
    this.helpTemplateUrl = ko.observable();
    this.isHelpTemplateLoading = ko.observable();
    this.selectedHelpTemplate = ko.observable();
    this.selectedHelpTemplate.subscribe((helpTemplateName) => {
        if (helpTemplateName) {
            this.isHelpTemplateLoading(true);
            this.helpTemplateUrl(arches.urls.help_template + `?template=${helpTemplateName}`);
        } else {
            this.helpTemplateUrl(null);
        }
    });

    this.shouldShowIncompleteWorkflowsModal = ko.observable(false);
    this.requestingUserIsSuperuser = ko.observable(false);

    this.incompleteWorkflows = ko.observableArray([]);
    this.incompleteWorkflows.subscribe((incompleteWorkflows) => {
        if (incompleteWorkflows.length) {
            this.shouldShowIncompleteWorkflowsModal(true);
        }
    });

    fetch(arches.urls.api_user_incomplete_workflows).then((resp) => {
        if (resp.ok) {
            return resp.json();
        } else {
            params.alert(new JsonErrorAlertViewModel('ep-alert-red', resp.responseJSON));
        }
    }).then((respJSON) => {
        this.incompleteWorkflows(respJSON.incomplete_workflows.map((workflowData) => {
            const datetime = new Date(workflowData.created);
            workflowData.created = datetime.toLocaleString();
            return workflowData;
        }));

        this.requestingUserIsSuperuser(respJSON.requesting_user_is_superuser);
    });
};

ko.components.register('init-workflow', {
    viewModel: InitWorkflow,
    template: initWorkflowTemplate
});

export default InitWorkflow;
