// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science

import arches from 'arches';
import ko from 'knockout';
import $ from 'jquery';
import Cookies from 'js-cookie';
import AlertViewModel from 'viewmodels/alert';
import {
    MULTI_Y_MEAN,
    MULTI_Y_REFERENCE,
    MULTI_Y_SEPARATE,
} from 'utils/xy-transforms';
import { getRendererConfig, invalidate } from 'utils/renderer-cache';
import importerConfigurationTemplate from 'templates/views/components/plugins/importer-configuration.htm';
// Arches' onEnterkeyClick / onSpaceClick, so a heading that toggles a section
// answers the keyboard as well as the mouse.
import 'bindings/key-events-click';
import 'bootstrap';
import 'bindings/select2-query';

const vm = function (params) {
    this.alert = params.alert;

    // The alert host comes from the page viewmodel, which the file renderer
    // does not always receive — `params?.pageVm?.alert` is undefined in the
    // resource editor. Calling it threw, and since the confirmation now runs on
    // every delete rather than only on a refusal, it threw every time.
    //
    // A destructive action must be confirmed one way or another, so fall back
    // to the browser's own dialog rather than skipping the question.
    const canAlert = () => typeof this.alert === 'function';

    const confirmThen = (title, text, onConfirm) => {
        if (canAlert()) {
            this.alert(
                new AlertViewModel('ep-alert-red', title, text, function () {}, onConfirm)
            );
            return;
        }
        if (window.confirm(`${title}\n\n${text}`)) onConfirm();
    };

    const notify = (title, text) => {
        if (canAlert()) {
            this.alert(new AlertViewModel('ep-alert-red', title, text));
            return;
        }
        window.alert(`${title}\n\n${text}`);
    };
    this.rendererConfigs = params.rendererConfigs || ko.observableArray();

    // The list is expected to grow into the hundreds as each lab adds its own
    // instruments' quirks. Filtering client-side keeps every keystroke instant;
    // the endpoint returns the whole set in one small payload, so paginating it
    // would buy a round trip and cost responsiveness.
    this.configFilter = ko.observable('');
    this.filteredConfigs = ko.pureComputed(() => {
        const needle = this.configFilter().trim().toLowerCase();
        const configs = this.rendererConfigs() || [];
        if (!needle) return configs;
        return configs.filter((configuration) => {
            const name = (ko.unwrap(configuration.name) || '').toLowerCase();
            const description = (
                ko.unwrap(configuration.description) || ''
            ).toLowerCase();
            // Descriptions carry the column layout, so a curator can search
            // "reference" or "m/z" and find the configuration that fits a file.
            return name.includes(needle) || description.includes(needle);
        });
    });
    this.noConfigMatches = ko.pureComputed(
        () => this.configFilter().trim() !== '' && this.filteredConfigs().length === 0
    );
    this.selectedConfiguration = params.selectedConfiguration || ko.observable();
    this.showConfigurationPanel = ko.observable();
    this.editConfigurationId = ko.observable(undefined);
    this.showImporterList = ko.observable(true);
    this.applyConfigurationVisible = ko.observable(false);
    this.configurationName = ko.observable();
    this.configurationDescription = ko.observable();
    this.headerConfig = ko.observable();
    this.footerConfig = ko.observable();
    this.headerDelimiter = ko.observable();
    this.footerDelimiter = ko.observable();
    this.invalidDelimiter = ko.observable(false);
    this.includeDelimiter = ko.observable();
    this.headerFixedLines = ko.observable();
    this.dataDelimiterRadio = ko.observable();
    this.chartTitle = ko.observable();
    this.xAxisLabel = ko.observable();
    this.yAxisLabel = ko.observable();
    this.dataDelimiter = ko.observable();

    // X column mode: 'data' (default) or 'generate'
    this.xColumnMode = ko.observable('data');

    // Feature 1: Spectral range filter

    // Descending X axis. Conventional for FTIR (4000 -> 400 cm-1), NMR and XPS;
    // plotting those ascending reads as an error to a spectroscopist.
    this.xReversed = ko.observable(false);

    // Feature 2: Axis unit presets
    this.xAxisPresets = [
        { text: 'cm\u207b\u00b9', value: 'cm\u207b\u00b9' },
        { text: 'nm', value: 'nm' },
        { text: 'eV', value: 'eV' },
        { text: '\u03bcm', value: '\u03bcm' },
        { text: 'Raman shift (cm\u207b\u00b9)', value: 'Raman shift (cm\u207b\u00b9)' },
        { text: 'Wavenumber (cm\u207b\u00b9)', value: 'Wavenumber (cm\u207b\u00b9)' },
        { text: 'Wavelength (nm)', value: 'Wavelength (nm)' },
        { text: 'Energy (eV)', value: 'Energy (eV)' },
    ];
    this.yAxisPresets = [
        { text: 'Counts', value: 'Counts' },
        { text: 'Absorbance', value: 'Absorbance' },
        { text: 'Transmittance (%)', value: 'Transmittance (%)' },
        { text: 'Reflectance (%)', value: 'Reflectance (%)' },
        { text: 'a.u.', value: 'a.u.' },
        { text: 'Intensity', value: 'Intensity' },
    ];

    // Feature 3: Column assignment
    this.yAxisRightLabel = ko.observable();
    this.columnAssignments = ko.observableArray([]);
    this.showColumnAssignment = ko.observable(false);
    // 'reference' and 'dark' let a curator describe a reference-normalised
    // acquisition declaratively — the FORS exports carry tgt_count / ref_count
    // side by side — instead of computing the reflectance by hand beforehand.
    this.columnRoleOptions = [
        { text: 'X', value: 'x' },
        { text: 'Y \u2190', value: 'yLeft' },
        { text: 'Y \u2192', value: 'yRight' },
        { text: arches.translations.xyRoleReference, value: 'reference' },
        { text: arches.translations.xyRoleDark, value: 'dark' },
        { text: 'Ignore', value: 'ignore' },
    ];
    this.addColumnAssignment = () => {
        this.columnAssignments.push({
            columnIndex: ko.observable(this.columnAssignments().length),
            role: ko.observable(
                this.columnAssignments().length === 0 ? 'x' : 'yLeft'
            ),
        });
    };
    this.removeColumnAssignment = (item) => {
        this.columnAssignments.remove(item);
    };
    this.hasYRightColumn = ko.pureComputed(() =>
        this.columnAssignments().some(
            (a) => ko.unwrap(a.role) === 'yRight'
        )
    );

    // ------------------------------------------------------------------
    // Several Y columns remain — what do we plot?
    // ------------------------------------------------------------------
    // One question, three mutually exclusive answers. It used to be two
    // independent settings — a "mean" select and a transformation chain — that
    // could both be set and, together, silently did nothing: the mean left a
    // single series carrying no reference role, so the normalisation found
    // nothing to divide by and handed the data back untouched.
    this.multiYHandling = ko.observable(MULTI_Y_SEPARATE);
    this.MULTI_Y_SEPARATE = MULTI_Y_SEPARATE;
    this.MULTI_Y_MEAN = MULTI_Y_MEAN;
    this.MULTI_Y_REFERENCE = MULTI_Y_REFERENCE;

    // Dividing by the reference is only offered once a column carries that
    // role — the dependency is structural, not a warning left to be read.
    this.referenceColumnDeclared = ko.pureComputed(() =>
        this.columnAssignments().some(
            (assignment) => ko.unwrap(assignment.role) === 'reference'
        )
    );

    // Untagging the reference column while normalising would leave a setting
    // that cannot run. Fall back rather than keep an inert choice.
    this.referenceColumnDeclared.subscribe((declared) => {
        if (!declared && this.multiYHandling() === MULTI_Y_REFERENCE) {
            this.multiYHandling(MULTI_Y_SEPARATE);
        }
    });

    this.onConfigSaved = params.onConfigSaved;

    // Sync showImporterList state to parent if provided
    if (params.showingList) {
        this.showImporterList.subscribe((val) => {
            params.showingList(val);
        });
        params.showingList(this.showImporterList());
    }

    this.dataDelimiterRadio.subscribe((value) => {
        if (value === 'auto') {
            this.dataDelimiter(undefined);
        } else if (value !== 'other') {
            this.dataDelimiter(value);
        } else {
            this.dataDelimiter('');
        }
    });

    this.renderer = 'e93b7b27-40d8-4141-996e-e59ff08742f3';

    this.cancelConfigEdit = () => {
        this.showConfigurationPanel(false);
        this.showImporterList(true);
    };

    // Opening the panel for a new configuration clears every field it owns.
    // Without this it only cleared the id, so a new configuration silently
    // inherited the title, labels and delimiter of the one last edited.
    this.startNewConfiguration = () => {
        this.editConfigurationId(undefined);
        this.configurationName(undefined);
        this.configurationDescription(undefined);
        this.headerConfig('none');
        this.headerDelimiter(undefined);
        this.headerFixedLines(undefined);
        this.footerConfig('none');
        this.footerDelimiter(undefined);
        // Also clears any stuck invalidDelimiter, through the radio subscription.
        this.dataDelimiterRadio('auto');
        this.includeDelimiter(undefined);
        this.xColumnMode('data');
        this.chartTitle(undefined);
        this.xAxisLabel(undefined);
        this.yAxisLabel(undefined);
        this.yAxisRightLabel('');
        this.xReversed(false);
        // Before multiYHandling: the referenceColumnDeclared guard downgrades
        // the choice whenever the column list changes.
        this.columnAssignments([]);
        this.showColumnAssignment(false);
        this.multiYHandling(MULTI_Y_SEPARATE);
        this.showConfigurationPanel(true);
        this.showImporterList(false);
    };

    this.dataDelimiter.subscribe((newDelimiter) => {
        if (!newDelimiter) {
            this.invalidDelimiter(false);
            return;
        }
        try {
            const valueRegex =
                newDelimiter.length < 2
                    ? new RegExp(`[${newDelimiter}\\s]+`)
                    : new RegExp(`${newDelimiter}`);
            this.invalidDelimiter(false);
        } catch (e) {
            this.invalidDelimiter(true);
        }
    });

    this.saveConfigEdit = async () => {
        const configId = this.editConfigurationId() ?? '';

        if (this.headerConfig() !== 'fixed') {
            this.headerFixedLines(undefined);
        }
        if (this.headerConfig() !== 'delimited') {
            this.headerDelimiter(undefined); // blank out previous values; don't save them.
        }
        if (this.footerConfig() !== 'delimited') {
            this.footerDelimiter(undefined); // blank out previous values; don't save them.
        }

        const xMode = this.xColumnMode();
        // Extract xColumnIndex from column assignments (find the column with role 'x')
        const xAssign = this.columnAssignments().find(
            (a) => ko.unwrap(a.role) === 'x'
        );
        const xColIdx = xAssign
            ? parseInt(ko.unwrap(xAssign.columnIndex), 10)
            : 0;
        const newConfiguration = {
            name: this.configurationName(),
            description: this.configurationDescription(),
            headerDelimiter: this.headerDelimiter(),
            footerDelimiter: this.footerDelimiter(),
            includeDelimiter: this.includeDelimiter(),
            headerFixedLines: this.headerFixedLines(),
            delimiterCharacter: this.dataDelimiter(),
            multiYHandling: this.multiYHandling(),
            xColumnMode: xMode === 'generate' ? 'generate' : undefined,
            xColumnIndex:
                xMode !== 'generate' && xColIdx !== 0
                    ? xColIdx
                    : undefined,
            display: {
                chartTitle: this.chartTitle(),
                xAxisLabel: this.xAxisLabel(),
                yAxisLabel: this.yAxisLabel(),
                xReversed: this.xReversed() ? true : undefined,
                yAxisRightLabel: this.yAxisRightLabel() || undefined,
                columnAssignments:
                    this.columnAssignments().length > 0
                        ? this.columnAssignments().map((a) => ({
                              columnIndex: parseInt(
                                  ko.unwrap(a.columnIndex),
                                  10
                              ),
                              role: ko.unwrap(a.role),
                          }))
                        : undefined,
            },
            rendererId: this.renderer,
        };

        const configSaveResponse = await fetch(
            `${arches.urls.renderer_config}${configId}`,
            {
                method: 'POST',
                credentials: 'include',
                body: JSON.stringify(newConfiguration),
                headers: {
                    'X-CSRFToken': Cookies.get('csrftoken'),
                },
            }
        );

        let responseJson = {};
        try {
            responseJson = await configSaveResponse.json();
        } catch {
            // no body — fall through to the generic refusal below
        }

        if (configSaveResponse.ok) {
            invalidate(this.renderer);
            await rendererConfigRefresh();
            if (this.onConfigSaved) {
                this.onConfigSaved();
            }
            this.showConfigurationPanel(false);
            this.showImporterList(true);
            return;
        }

        // The panel stays open on a refusal: closing it would throw away the
        // edit that was just refused, and leave the rejection indistinguishable
        // from a save. Same shape as performDelete below.
        notify(
            responseJson.reason === 'protected'
                ? arches.translations.configurationProtected
                : arches.translations.configurationNotSaved,
            responseJson.message || arches.translations.configurationNotSavedWarning
        );
    };

    const rendererConfigRefresh = async () => {
        try {
            const renderers = await getRendererConfig(this.renderer);
            const configs = renderers?.configs;
            this.rendererConfigs(configs);
        } catch {
            this.rendererConfigs([]);
        }
    };

    this.loadConfiguration = (configuration) => {
        this.configurationName(configuration.name);
        this.configurationDescription(configuration.description);
        const delimiterCharacter = configuration.config.delimiterCharacter;
        if (configuration.config?.headerFixedLines) {
            this.headerConfig('fixed');
            this.headerFixedLines(configuration.config.headerFixedLines);
        } else if (configuration.config?.headerDelimiter) {
            this.headerConfig('delimited');
            this.headerDelimiter(configuration.config.headerDelimiter);
        } else {
            this.headerConfig('none');
        }

        if (configuration.config?.footerDelimiter) {
            this.footerConfig('delimited');
            this.footerDelimiter(configuration.config.footerDelimiter);
        } else {
            this.footerConfig('none');
        }

        const radioValue = !delimiterCharacter
            ? 'auto'
            : delimiterCharacter === ',' || delimiterCharacter === '|'
                ? delimiterCharacter
                : 'other';
        this.dataDelimiterRadio(radioValue);
        if (radioValue === 'other') {
            this.dataDelimiter(delimiterCharacter);
        }
        this.editConfigurationId(configuration.configid);
        this.includeDelimiter(configuration?.config?.includeDelimiter);

        // X column mode
        const xMode = configuration?.config?.xColumnMode;
        this.xColumnMode(xMode === 'generate' ? 'generate' : 'data');
        this.chartTitle(configuration?.config?.display?.chartTitle);
        this.xAxisLabel(configuration?.config?.display?.xAxisLabel);
        this.yAxisLabel(configuration?.config?.display?.yAxisLabel);

        this.xReversed(!!configuration?.config?.display?.xReversed);

        // Feature 3: Column assignment
        this.yAxisRightLabel(
            configuration?.config?.display?.yAxisRightLabel ?? ''
        );
        const assignments =
            configuration?.config?.display?.columnAssignments;
        if (assignments && Array.isArray(assignments)) {
            this.columnAssignments(
                assignments.map((a) => ({
                    columnIndex: ko.observable(a.columnIndex),
                    role: ko.observable(a.role),
                }))
            );
            this.showColumnAssignment(true);
        } else {
            this.columnAssignments([]);
            this.showColumnAssignment(false);
        }

        // Must follow columnAssignments: the referenceColumnDeclared guard
        // downgrades this choice whenever the column list changes.
        this.multiYHandling(
            configuration?.config?.multiYHandling || MULTI_Y_SEPARATE
        );

        this.showConfigurationPanel(true);
        this.showImporterList(false);
    };

    // Deleting was a single unguarded click on a bin icon, and a configuration
    // several files still point at could go with it. Ask first, name what is
    // about to go, and say plainly that it cannot be undone.
    this.deleteConfiguration = (configuration) => {
        confirmThen(
            arches.translations.deleteConfigurationTitle,
            arches.translations.deleteConfigurationWarning.replace(
                '{name}',
                ko.unwrap(configuration.name)
            ),
            () => this.performDelete(configuration)
        );
    };

    this.performDelete = async (configuration) => {
        const configDeleteResponse = await fetch(
            `${arches.urls.renderer_config}${configuration.configid}`,
            {
                method: 'DELETE',
                credentials: 'include',
                headers: {
                    'X-CSRFToken': Cookies.get('csrftoken'),
                },
            }
        );

        let responseJson = {};
        try {
            responseJson = await configDeleteResponse.json();
        } catch {
            // no body — fall through to the generic refusal below
        }

        if (configDeleteResponse.ok && responseJson.deleted) {
            invalidate(this.renderer);
            await rendererConfigRefresh();
            if (this.onConfigSaved) {
                this.onConfigSaved();
            }
            return;
        }

        // A refusal carries its reason: the server knows whether the
        // configuration is part of the shared baseline or merely still in use.
        notify(
            responseJson.reason === 'protected'
                ? arches.translations.configurationProtected
                : arches.translations.importerInUse,
            responseJson.message || arches.translations.importerInUseWarning
        );
    };

    rendererConfigRefresh();
};

export default ko.components.register('importer-configuration', {
    viewModel: vm,
    template: importerConfigurationTemplate,
});