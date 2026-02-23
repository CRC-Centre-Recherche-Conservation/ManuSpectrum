// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science

import arches from 'arches';
import ko from 'knockout';
import $ from 'jquery';
import Cookies from 'js-cookie';
import xyParser from 'utils/xy-parser';
import AlertViewModel from 'viewmodels/alert';
import { getRendererConfig, invalidate } from 'utils/renderer-cache';
import importerConfigurationTemplate from 'templates/views/components/plugins/importer-configuration.htm';
import 'bootstrap';
import 'bindings/select2-query';

const vm = function (params) {
    this.alert = params.alert;
    this.rendererConfigs = params.rendererConfigs || ko.observableArray();
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
    this.delimiterCharacter = ko.observable();
    this.invalidDelimiter = ko.observable(false);
    this.includeDelimiter = ko.observable();
    this.headerFixedLines = ko.observable();
    this.dataDelimiterRadio = ko.observable();
    this.chartTitle = ko.observable();
    this.xAxisLabel = ko.observable();
    this.yAxisLabel = ko.observable();
    this.dataDelimiter = ko.observable();
    this.placeholder = arches.translations.selectTransformation;

    // X column mode: 'data' (default) or 'generate'
    this.xColumnMode = ko.observable('data');
    this.xGenerateStart = ko.observable();
    this.xGenerateEnd = ko.observable();

    // Feature 1: Spectral range filter
    this.xRangeMin = ko.observable();
    this.xRangeMax = ko.observable();
    this.showAdvancedDisplay = ko.observable(false);

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
    this.columnRoleOptions = [
        { text: 'X', value: 'x' },
        { text: 'Y \u2190', value: 'yLeft' },
        { text: 'Y \u2192', value: 'yRight' },
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

    const transformations = xyParser.transformations().map((transform) => {
        return {
            text: transform,
            id: transform,
        };
    });

    this.xyTransformations = ko.observable(transformations);
    this.selectedTransformation = ko.observable();
    this.onConfigSaved = params.onConfigSaved;

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
        const newConfiguration = {
            name: this.configurationName(),
            description: this.configurationDescription(),
            headerDelimiter: this.headerDelimiter(),
            footerDelimiter: this.footerDelimiter(),
            includeDelimiter: this.includeDelimiter(),
            headerFixedLines: this.headerFixedLines(),
            delimiterCharacter: this.dataDelimiter(),
            transformation: this.selectedTransformation(),
            xColumnMode: xMode === 'generate' ? 'generate' : undefined,
            xGenerateStart:
                xMode === 'generate' &&
                this.xGenerateStart() !== '' &&
                this.xGenerateStart() !== undefined
                    ? parseFloat(this.xGenerateStart())
                    : undefined,
            xGenerateEnd:
                xMode === 'generate' &&
                this.xGenerateEnd() !== '' &&
                this.xGenerateEnd() !== undefined
                    ? parseFloat(this.xGenerateEnd())
                    : undefined,
            display: {
                chartTitle: this.chartTitle(),
                xAxisLabel: this.xAxisLabel(),
                yAxisLabel: this.yAxisLabel(),
                xRangeMin:
                    this.xRangeMin() !== '' &&
                    this.xRangeMin() !== undefined
                        ? parseFloat(this.xRangeMin())
                        : undefined,
                xRangeMax:
                    this.xRangeMax() !== '' &&
                    this.xRangeMax() !== undefined
                        ? parseFloat(this.xRangeMax())
                        : undefined,
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

        if (configSaveResponse.ok) {
            invalidate(this.renderer);
            await rendererConfigRefresh();
            if (this.onConfigSaved) {
                this.onConfigSaved();
            }
        }

        this.showConfigurationPanel(false);
        this.showImporterList(true);
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
        this.selectedTransformation(configuration?.config?.transformation);

        // X column mode
        const xMode = configuration?.config?.xColumnMode;
        this.xColumnMode(xMode === 'generate' ? 'generate' : 'data');
        this.xGenerateStart(configuration?.config?.xGenerateStart ?? '');
        this.xGenerateEnd(configuration?.config?.xGenerateEnd ?? '');
        this.chartTitle(configuration?.config?.display?.chartTitle);
        this.xAxisLabel(configuration?.config?.display?.xAxisLabel);
        this.yAxisLabel(configuration?.config?.display?.yAxisLabel);

        // Feature 1: Spectral range
        const xMin = configuration?.config?.display?.xRangeMin;
        const xMax = configuration?.config?.display?.xRangeMax;
        this.xRangeMin(xMin ?? '');
        this.xRangeMax(xMax ?? '');
        this.showAdvancedDisplay(xMin !== undefined || xMax !== undefined);

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

        this.showConfigurationPanel(true);
        this.showImporterList(false);
    };

    this.deleteConfiguration = async (configuration) => {
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

        if (configDeleteResponse.ok) {
            const responseJson = await configDeleteResponse.json();
            if (responseJson.deleted) {
                invalidate(this.renderer);
                await rendererConfigRefresh();
                if (this.onConfigSaved) {
                    this.onConfigSaved();
                }
            } else {
                this.alert(
                    new AlertViewModel(
                        'ep-alert-red',
                        arches.translations.importerInUse,
                        arches.translations.importerInUseWarning
                    )
                );
            }
        }
    };

    rendererConfigRefresh();
};

export default ko.components.register('importer-configuration', {
    viewModel: vm,
    template: importerConfigurationTemplate,
});