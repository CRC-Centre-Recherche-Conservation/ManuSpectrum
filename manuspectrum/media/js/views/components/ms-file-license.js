/**
 * Licence notice of one stored file, and its picker when `editable`.
 *
 * Params:
 *   entry     one entry of a `file-list` value (plain or mapped by knockout-mapping)
 *   files     the observable array holding `entry`: notified on each write,
 *             and read by the notice so it follows another instance's writes
 *   editable  show the licence form above the notice
 *
 * The picker opens on the stored licence, or on the default when there is
 * none, and writes `entry.license` only when the curator changes it.
 */

import arches from 'arches';
import ko from 'knockout';
import dispose from 'utils/dispose';
import {
    catalogueFrom,
    licenseToStore,
    noticeParts,
    resolveLicense,
    writeLicense,
} from 'utils/file-license';
import fileLicenseTemplate from 'templates/views/components/ms-file-license.htm';

const viewModel = function(params) {
    const self = this;
    const catalogue = catalogueFrom(arches.translations.licenseCatalogue);
    const entry = params.entry;
    const stored = ko.toJS(entry.license) || {};
    const isCustom = stored.id === catalogue.customId;

    this.editable = !!params.editable;
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

    this.current = ko.pureComputed(() => {
        if (self.editable) {
            return choice();
        }
        ko.unwrap(params.files);
        return ko.toJS(entry.license);
    });
    this.resolved = ko.pureComputed(() => resolveLicense(self.current(), catalogue));
    this.customIsIncomplete = ko.pureComputed(() =>
        self.isCustom() && self.resolved()?.id !== catalogue.customId
    );
    this.parts = ko.pureComputed(() =>
        noticeParts({ ...entry, license: self.current() }, catalogue, arches.activeLanguage)
    );

    if (this.editable) {
        this.disposables.push(
            choice.subscribe((value) => writeLicense(entry, value, params.files))
        );
    }

    this.dispose = () => dispose(self);
};

export default ko.components.register('ms-file-license', {
    viewModel: viewModel,
    template: fileLicenseTemplate,
});
