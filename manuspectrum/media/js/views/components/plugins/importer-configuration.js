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
    this.placeholder = arches.translations.selectColumnCombination;

    // X column mode: 'data' (default) or 'generate'
    this.xColumnMode = ko.observable('data');
    this.xGenerateStart = ko.observable();
    this.xGenerateEnd = ko.observable();

    // Feature 1: Spectral range filter
    this.xRangeMin = ko.observable();
    this.xRangeMax = ko.observable();
    this.showAdvancedDisplay = ko.observable(false);

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

    const transformations = xyParser.transformations().map((transform) => {
        return {
            text: transform,
            id: transform,
        };
    });

    this.xyTransformations = ko.observable(transformations);
    this.selectedTransformation = ko.observable();

    // ------------------------------------------------------------------
    // Transformation chain
    // ------------------------------------------------------------------
    // Applied in order to the plotted spectrum, never to the stored file.
    // Transforms flagged `analystOnly` need a parameter the analyst chooses, so
    // they are offered here but never shipped inside a technique preset: a
    // researcher must be able to trust that an axis they did not configure
    // shows the numbers that are in the file.
    this.availableTransforms = [
        {
            value: 'reference-normalize',
            text: arches.translations.xyTransformReferenceNormalize,
            analystOnly: false,
        },
        {
            value: 'log-inverse-r',
            text: arches.translations.xyTransformLogInverseR,
            analystOnly: false,
        },
        {
            value: 'kubelka-munk',
            text: arches.translations.xyTransformKubelkaMunk,
            analystOnly: false,
        },
        {
            value: 'normalize-max',
            text: arches.translations.xyTransformNormalizeMax,
            analystOnly: false,
        },
        {
            value: 'normalize-area',
            text: arches.translations.xyTransformNormalizeArea,
            analystOnly: false,
        },
        {
            value: 'smooth',
            text: arches.translations.xyTransformSmooth,
            analystOnly: true,
        },
        {
            value: 'derivative',
            text: arches.translations.xyTransformDerivative,
            analystOnly: true,
        },
    ];

    const PARAMETERISED_TRANSFORMS = ['smooth', 'derivative'];

    this.transformChain = ko.observableArray([]);
    this.showTransforms = ko.observable(false);

    const makeTransformStep = (step) => {
        const type = ko.observable(step?.type || 'reference-normalize');
        return {
            type: type,
            window: ko.observable(step?.window ?? ''),
            polyOrder: ko.observable(step?.polyOrder ?? ''),
            order: ko.observable(step?.order ?? ''),
            // Parameter inputs only make sense for the Savitzky-Golay pair.
            showsParameters: ko.pureComputed(() =>
                PARAMETERISED_TRANSFORMS.includes(ko.unwrap(type))
            ),
            isDerivative: ko.pureComputed(
                () => ko.unwrap(type) === 'derivative'
            ),
        };
    };

    this.addTransform = () => {
        this.transformChain.push(makeTransformStep());
    };
    this.removeTransform = (step) => {
        this.transformChain.remove(step);
    };
    // Order is meaningful: a baseline or smoothing step must run before a
    // normalisation, or the normalisation scales the noise it was meant to
    // remove. Curators reorder by moving steps rather than re-adding them.
    const moveTransform = (step, offset) => {
        const chain = this.transformChain();
        const index = chain.indexOf(step);
        const target = index + offset;
        if (index < 0 || target < 0 || target >= chain.length) return;
        this.transformChain.splice(index, 1);
        this.transformChain.splice(target, 0, step);
    };
    this.moveTransformUp = (step) => moveTransform(step, -1);
    this.moveTransformDown = (step) => moveTransform(step, 1);

    // Reference normalisation is opt-in: it divides by the column tagged as the
    // white reference, and returns the data untouched when no column carries
    // that role. Silently doing nothing is the worst outcome — a curator adds
    // the step, sees both raw series still plotted, and has no way to tell
    // whether the transform ran. So say it plainly, right where it is fixed.
    this.referenceNormalizeNeedsColumn = ko.pureComputed(() => {
        const inChain = this.transformChain().some(
            (step) => ko.unwrap(step.type) === 'reference-normalize'
        );
        if (!inChain) return false;
        return !this.columnAssignments().some(
            (assignment) => ko.unwrap(assignment.role) === 'reference'
        );
    });


    // Serialise the chain, dropping empty parameters so a step keeps the
    // engine's own defaults rather than persisting a blank string.
    const buildTransformChain = () => {
        const chain = this.transformChain()
            .map((step) => {
                const type = ko.unwrap(step.type);
                if (!type) return null;
                const serialised = { type: type };
                if (PARAMETERISED_TRANSFORMS.includes(type)) {
                    const window = parseInt(ko.unwrap(step.window), 10);
                    const polyOrder = parseInt(ko.unwrap(step.polyOrder), 10);
                    if (!isNaN(window)) serialised.window = window;
                    if (!isNaN(polyOrder)) serialised.polyOrder = polyOrder;
                    if (type === 'derivative') {
                        const order = parseInt(ko.unwrap(step.order), 10);
                        if (!isNaN(order)) serialised.order = order;
                    }
                }
                return serialised;
            })
            .filter(Boolean);
        return chain.length > 0 ? chain : undefined;
    };
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
            transformation: this.selectedTransformation(),
            // Read by utils/xy-transforms at plot time. Kept at the top level of
            // the config, alongside the parsing options, because it describes
            // the data rather than the chart.
            transforms: buildTransformChain(),
            xColumnMode: xMode === 'generate' ? 'generate' : undefined,
            xColumnIndex:
                xMode !== 'generate' && xColIdx !== 0
                    ? xColIdx
                    : undefined,
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
                xReversed: this.xReversed() ? true : undefined,
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
        this.xReversed(!!configuration?.config?.display?.xReversed);
        this.showAdvancedDisplay(xMin !== undefined || xMax !== undefined);

        // Transformation chain
        const chain = configuration?.config?.transforms;
        if (Array.isArray(chain) && chain.length > 0) {
            this.transformChain(
                chain
                    .map((step) =>
                        typeof step === 'string' ? { type: step } : step
                    )
                    .filter((step) => step && step.type)
                    .map(makeTransformStep)
            );
            this.showTransforms(true);
        } else {
            this.transformChain([]);
            this.showTransforms(false);
        }

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