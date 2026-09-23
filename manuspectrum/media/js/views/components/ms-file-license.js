/**
 * Licence of one stored file: the notice, the report row, or the picker.
 *
 * Params:
 *   entry     one entry of a `file-list` value (plain or mapped by knockout-mapping)
 *   tile      the tile holding `entry`; writes wake its snapshot once (see
 *             `writeLicense`) and the notice follows it
 *   editable  show the licence form above the notice
 *   report    show the report row (file name and licence) instead of the notice
 *
 * The picker opens on the stored licence, or on the default when there is
 * none, and writes `entry.license` only when the curator changes it. Without
 * a catalogue the component renders nothing.
 */

import arches from 'arches';
import ko from 'knockout';
import dispose from 'utils/dispose';
import {
    catalogueFrom,
    licenseToStore,
    noticeParts,
    readLicense,
    reportParts,
    resolveLicense,
    writeLicense,
} from 'utils/file-license';
import fileLicenseTemplate from 'templates/views/components/ms-file-license.htm';

const viewModel = function(params) {
    const self = this;
    const catalogue = catalogueFrom(arches.translations.licenseCatalogue);
    const entry = params.entry;
    const tile = params.tile;
    const stored = ko.toJS(entry.license) || {};
    const isCustom = !!stored.id && stored.id === catalogue.customId;

    this.hasCatalogue = catalogue.licenses.length > 0;
    this.editable = !!ko.unwrap(params.editable) && this.hasCatalogue;
    this.report = !!params.report;
    this.licenses = catalogue.licenses;
    this.selectedId = ko.observable(
        isCustom || catalogue.byId.has(stored.id) ? stored.id : catalogue.defaultId
    );
    this.customLabel = ko.observable(isCustom ? stored.label || '' : '');
    this.customUrl = ko.observable(isCustom ? stored.url || '' : '');
    this.isCustom = ko.pureComputed(() => self.selectedId() === catalogue.customId);

    const choice = ko.computed(() =>
        licenseToStore(self.selectedId(), self.customLabel(), self.customUrl(), catalogue)
    );
    this.disposables = [choice];

    this.current = ko.pureComputed(() =>
        self.editable ? choice() : readLicense(entry, tile)
    );
    this.resolved = ko.pureComputed(() => resolveLicense(self.current(), catalogue));
    this.customIsIncomplete = ko.pureComputed(() =>
        self.isCustom() && self.resolved()?.id !== catalogue.customId
    );
    this.parts = ko.pureComputed(() => {
        const shown = { ...entry, license: self.current() };
        return self.report
            ? reportParts(shown, catalogue)
            : noticeParts(shown, catalogue, arches.activeLanguage);
    });

    if (this.editable) {
        this.disposables.push(
            choice.subscribe((value) => writeLicense(entry, value, tile))
        );
    }

    this.dispose = () => dispose(self);
};

export default ko.components.register('ms-file-license', {
    viewModel: viewModel,
    template: fileLicenseTemplate,
});
