/**
 * Import Biblissima workflow — step 4 (Summary / Colophon).
 *
 * Reads the artefacts produced by step 3 (`createStepData`) and the
 * project context from step 1 (`configStepData`) and exposes them to
 * the template as a single, calm read of the import outcome:
 *
 *   - hero count of created resources
 *   - secondary stats for linked / skipped / errored items
 *   - thumbnail-bearing list of created resources
 *   - compact list of items merged into existing Arches resources
 *   - CTA back to the parent project
 *
 * No DB writes here, no further fetches — the template is the colophon
 * at the end of the workflow.
 */
import ko from 'knockout';
import arches from 'arches';
import 'bindings/thumb-fallback';
import importBiblissimaFinalStepTemplate from 'templates/views/components/workflows/import-biblissima-workflow/import-biblissima-final-step.htm';

const viewModel = function(params) {
    const self = this;

    this.loading = ko.observable(false);
    this.complete = params.form?.complete || ko.observable(true);

    // Data from previous steps
    this.createData = params.createStepData || {};
    this.configData = params.configStepData || {};

    this.createdResources = ko.observableArray(this.createData.createdResources || []);
    this.linkedResources = ko.observableArray(this.createData.linkedResources || []);
    this.skippedCount = ko.observable(this.createData.skippedCount || 0);
    this.errorCount = ko.observable(this.createData.errorCount || 0);
    this.resourceType = this.createData.resourceType || 'Document';
    this.projectId = this.createData.projectId || null;
    this.projectName = this.configData.projectName || '';

    this.createdCount = ko.computed(() => self.createdResources().length);
    this.linkedCount = ko.computed(() => self.linkedResources().length);

    this.hasCreated = ko.computed(() => self.createdCount() > 0);
    this.hasLinked = ko.computed(() => self.linkedCount() > 0);
    this.hasIssues = ko.computed(
        () => self.skippedCount() > 0 || self.errorCount() > 0
    );

    // Progressive disclosure: keep the page short for big imports.
    // Show the first PREVIEW_LIMIT items; the rest hide behind a
    // toggle so a 25-entry import doesn't turn into a 25-row scroll
    // wall before the user even sees the project CTA.
    const PREVIEW_LIMIT = 6;
    this.createdExpanded = ko.observable(false);
    this.linkedExpanded = ko.observable(false);

    this.visibleCreatedResources = ko.computed(() => {
        const all = self.createdResources();
        return self.createdExpanded() ? all : all.slice(0, PREVIEW_LIMIT);
    });
    this.visibleLinkedResources = ko.computed(() => {
        const all = self.linkedResources();
        return self.linkedExpanded() ? all : all.slice(0, PREVIEW_LIMIT);
    });

    this.createdHiddenCount = ko.computed(() =>
        Math.max(0, self.createdCount() - PREVIEW_LIMIT)
    );
    this.linkedHiddenCount = ko.computed(() =>
        Math.max(0, self.linkedCount() - PREVIEW_LIMIT)
    );

    this.toggleCreatedExpanded = () =>
        self.createdExpanded(!self.createdExpanded());
    this.toggleLinkedExpanded = () =>
        self.linkedExpanded(!self.linkedExpanded());

    // Translatable label for the resource type. Plain strings here so
    // the value can be read out of arches.translations cleanly; falls
    // back to the raw value if no translation key matches.
    this.resourceTypeLabel = ko.computed(() => {
        const t = arches.translations || {};
        if (self.resourceType === 'Document') {
            return t.biblissimaResourceTypeDocument || 'Manuscript';
        }
        if (self.resourceType === 'Component') {
            return t.biblissimaResourceTypeComponent || 'Illumination';
        }
        return self.resourceType;
    });

    this.resourceUrl = (resourceId) => `/resource/${resourceId}`;
    this.projectUrl = ko.computed(() =>
        self.projectId ? `/resource/${self.projectId}` : null
    );

    // Display helper: prefer label, fallback to ARK, fallback to "—"
    // so the row never collapses to a blank link.
    this.resourceDisplayLabel = (item) =>
        item.label || item.arkId || item.resourceId || '—';

    // Compose a short manuscript / folio caption shown under each
    // created resource — kept terse so the grid stays scannable.
    this.resourceCaption = (item) => {
        const parts = [];
        if (item.shelfmark) parts.push(item.shelfmark);
        else if (item.manuscript) parts.push(item.manuscript);
        if (item.folio) parts.push(`f. ${item.folio}`);
        if (item.date) parts.push(item.date);
        return parts.join(' · ');
    };
};

ko.components.register('import-biblissima-final-step', {
    viewModel: viewModel,
    template: importBiblissimaFinalStepTemplate,
});

export default viewModel;
