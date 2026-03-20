// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science

import ko from 'knockout';
import arches from 'arches';
import SummaryStep from 'views/components/workflows/summary-step';
import createProjectFinalStepTemplate from 'templates/views/components/workflows/create-project-workflow/create-project-final-step.htm';

const DOCUMENT_GRAPH_ID = '0c8226c1-11a9-4c48-9601-a7a0c6f2df6b';

const viewModel = function(params) {
    const self = this;
    SummaryStep.apply(this, [params]);

    this.resourceLoading = ko.observable(true);
    this.documentsLoading = ko.observable(true);

    this.documentGraphId = params.documentGraphId || DOCUMENT_GRAPH_ID;
    this.studiedDocuments = ko.observableArray();

    this.loadRelatedDocuments = async () => {
        try {
            const response = await window.fetch(`${arches.urls.related_resources}${self.resourceid}`);
            const data = await response.json();

            const documents = data.related_resources.related_resources.filter(
                rr => rr.graph_id === self.documentGraphId
            );

            documents.forEach((doc) => {
                self.studiedDocuments.push({
                    resourceid: doc.resourceinstanceid,
                    name: doc.displayname,
                });
            });

            self.documentsLoading(false);
            if (!self.resourceLoading()) {
                self.loading(false);
            }
        } catch (e) {
            console.error('Error loading related documents:', e);
            self.documentsLoading(false);
        }
    };

    this.loadRelatedDocuments();

    this.resourceData.subscribe(function(val) {
        this.displayName = val.displayname || 'unnamed';
        this.displaydescription = val.displaydescription || "none";

        this.reportVals = {
            projectName: {
                name: arches.translations.projectName,
                value: this.getResourceValue(val.resource['Name']?.[0], ['Label of name', '@display_value']) ||
                       this.displayName
            },
            projectTimespan: {
                name: arches.translations.projectTimespan,
                value: this.getResourceValue(val.resource['Period activity']?.[0], ['Start date of period activity', '@display_value'])
            },
            projectTeam: {
                name: arches.translations.projectTeam,
                value: this.getResourceValue(val.resource, ['Carried out by Actor', '@display_value'])
            },
        };

        const findStatement = (type) => {
            try {
                self.reportVals.statements = val.resource['Statement']?.map((statement) => ({
                    content: {
                        name: arches.translations.projectStatement,
                        value: self.getResourceValue(statement, ['Content of statement', '@display_value'])
                    },
                    type: {
                        name: arches.translations.type,
                        value: self.getResourceValue(statement, ['Type of statement', '@display_value'])
                    }
                })) || [];
            } catch (e) {
                self.reportVals.statements = [];
            }
            const foundStatement = self.reportVals.statements.find((statement) => {
                return statement.type?.value?.split(",").indexOf(type) > -1;
            });
            return foundStatement ? foundStatement.content : { name: arches.translations.projectStatement, value: 'None' };
        };

        this.reportVals.projectStatement = findStatement('brief text');

        this.resourceLoading(false);
        if (!this.documentsLoading()) {
            this.loading(false);
        }
    }, this);
};

ko.components.register('create-project-final-step', {
    viewModel: viewModel,
    template: createProjectFinalStepTemplate
});

export default viewModel;
