// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science


import $ from 'jquery';
import arches from 'arches';
import ko from 'knockout';
import afsReaderTemplate from 'templates/views/components/cards/file-renderers/xy-reader.htm';
import AfsInstrumentViewModel from 'viewmodels/afs-instrument';
import Cookies from 'js-cookie';
import XyParser from 'utils/xy-parser';
import dispose from 'utils/dispose';
import { getRendererConfig, invalidate, parseOverrides } from 'utils/renderer-cache';
import 'bindings/plotly';
import 'views/components/plugins/importer-configuration';

export default ko.components.register('xy-reader', {
    viewModel: function (params) {
        const self = this;
        this.alert = params?.pageVm?.alert;
        this.showConfigAdd = ko.observable(false);
        this.configName = ko.observable();
        this.delimiterCharacter = ko.observable();
        this.invalidDelimiter = ko.observable(false);
        this.headerDelimiter = ko.observable();
        this.headerFixedLines = ko.observable();
        this.selectedConfig = params.selectedConfig || ko.observable();
        this.selectedFile = params.selectedFile || ko.observable();
        this.selectedConfiguration = undefined;
        AfsInstrumentViewModel.apply(this, [params]);
        this.disposables = [];

        // set defaults for chart title/axis
        this.chartTitle(arches.translations.data);
        this.xAxisLabel(arches.translations.xAxis);
        this.yAxisLabel(arches.translations.yAxis);

        this.rendererConfigs = ko.observable([]);

        // on init, get available renderer configs for display to user.
        const rendererConfigRefresh = async () => {
            try {
                const renderers = await getRendererConfig(self.renderer);
                const configs = renderers?.configs;
                this.rendererConfigs(configs);
                const displayContent =
                    self.fileViewer?.displayContent() ||
                    self.displayContent;
                if (displayContent) {
                    const tile = displayContent.tile;

                    // displayContent is formatted differently from the core file viewer.
                    const configId = tile
                        ? ko.unwrap(
                              tile.data[self.fileViewer.fileListNodeId]
                          )?.[0]?.rendererConfig
                        : displayContent?.rendererConfig;

                    if (configId) {
                        this.selectedConfig(ko.unwrap(configId));
                    }
                }
            } catch {
                // fetch failed, leave configs empty
            }
        };

        this.disposables.push(this.selectedConfig.subscribe((config) => {
            if (
                !config ||
                (this.selectedFile() &&
                    this.selectedFile().url !== this.displayContent.url)
            ) {
                return;
            }
            this.selectedConfiguration = this.rendererConfigs().find(
                (currentConfig) => {
                    return currentConfig.configid === config;
                }
            );
            self.render();
            if (self.fileViewer?.displayContent()) {
                const tile = self.fileViewer.displayContent().tile;
                const node = ko.unwrap(
                    tile.data[self.fileViewer.fileListNodeId]
                );
                const currentRendererConfig = ko.unwrap(
                    node[0].rendererConfig
                );
                if (config !== currentRendererConfig) {
                    node[0].rendererConfig = config;
                    tile.save();
                }
            }
            const display = this.selectedConfiguration?.config?.display;
            this.chartTitle(
                display?.chartTitle
                    ? display.chartTitle
                    : arches.translations.data
            );
            this.xAxisLabel(
                display?.xAxisLabel
                    ? display.xAxisLabel
                    : arches.translations.xAxis
            );
            this.yAxisLabel(
                display?.yAxisLabel
                    ? display.yAxisLabel
                    : arches.translations.yAxis
            );
            this._xRangeMin = display?.xRangeMin;
            this._xRangeMax = display?.xRangeMax;
            this._columnAssignments = display?.columnAssignments || null;
            this.yAxisRightLabel(display?.yAxisRightLabel || '');
        }));

        rendererConfigRefresh();

        // Rename the core "Edit" tab to "Visualization"
        setTimeout(() => {
            $('.workbench-card-sidebar-tab').each(function () {
                const bind = $(this).attr('data-bind') || '';
                if (bind.includes("toggleTab('edit')")) {
                    $(this)
                        .find('i.fa')
                        .removeClass('fa-pencil')
                        .addClass('fa-eye');
                    $(this)
                        .find('.map-sidebar-text')
                        .text('Viz');
                }
            });
        }, 0);

        // --- Batch apply config to staged tiles ---
        this.batchApplying = ko.observable(false);
        this.batchResult = ko.observable('');

        this.stagedXyTileCount = ko.pureComputed(() => {
            const card = self.fileViewer?.card;
            if (!card || !card.staging) return 0;
            const stagingIds = card.staging();
            if (!stagingIds.length) return 0;
            const tiles = card.tiles();
            let count = 0;
            stagingIds.forEach((tileid) => {
                const tile = tiles.find((t) => t.tileid == tileid);
                if (tile) {
                    const node = ko.unwrap(
                        tile.data[self.fileViewer.fileListNodeId]
                    );
                    if (
                        node &&
                        node.length > 0 &&
                        ko.unwrap(node[0].renderer) === self.renderer
                    ) {
                        count++;
                    }
                }
            });
            return count;
        });

        this.batchMode = ko.pureComputed(
            () => self.stagedXyTileCount() > 0
        );

        this.canApplyBatch = ko.pureComputed(
            () => self.stagedXyTileCount() > 0 && !!self.selectedConfig()
        );

        this.applyConfigToStaged = async () => {
            const card = self.fileViewer?.card;
            if (!card || !card.staging) return;

            const configId = self.selectedConfig();
            if (!configId) return;

            self.batchApplying(true);
            self.batchResult('');

            const stagingIds = card.staging();
            const tiles = card.tiles();
            let applied = 0;
            let errors = 0;

            for (const tileid of stagingIds) {
                const tile = tiles.find((t) => t.tileid == tileid);
                if (!tile) continue;
                const node = ko.unwrap(
                    tile.data[self.fileViewer.fileListNodeId]
                );
                if (
                    !node ||
                    !node.length ||
                    ko.unwrap(node[0].renderer) !== self.renderer
                ) {
                    continue;
                }
                try {
                    node[0].rendererConfig = configId;
                    await tile.save();
                    applied++;
                } catch (e) {
                    console.error('Batch config save error:', tileid, e);
                    errors++;
                }
            }

            self.batchApplying(false);
            if (errors > 0) {
                self.batchResult(
                    applied +
                        ' applied, ' +
                        errors +
                        ' error(s)'
                );
            } else {
                self.batchResult(
                    'Config applied to ' + applied + ' file(s)'
                );
            }

            setTimeout(() => {
                self.batchResult('');
            }, 5000);
        };

        // --- Feature 1: Staged XY files with config status ---
        this.stagedXyFiles = ko.pureComputed(() => {
            const card = self.fileViewer?.card;
            if (!card || !card.staging) return [];
            const stagingIds = card.staging();
            const tiles = card.tiles();
            const configs = self.rendererConfigs();
            return stagingIds
                .map((tileid) => {
                    const tile = tiles.find((t) => t.tileid == tileid);
                    if (!tile) return null;
                    const node = ko.unwrap(
                        tile.data[self.fileViewer.fileListNodeId]
                    );
                    if (
                        !node?.length ||
                        ko.unwrap(node[0].renderer) !== self.renderer
                    )
                        return null;
                    const configId = ko.unwrap(node[0].rendererConfig);
                    const cfg = configs.find(
                        (c) => c.configid === configId
                    );
                    return {
                        name: ko.unwrap(node[0].name) || 'Unknown',
                        hasConfig: !!configId,
                        configName: cfg?.name || null,
                        tileid: tileid,
                    };
                })
                .filter(Boolean);
        });

        // --- Feature 4: All XY files overview ---
        this.allXyFiles = ko.pureComputed(() => {
            const card = self.fileViewer?.card;
            if (!card) return [];
            const tiles = card.tiles();
            const configs = self.rendererConfigs();
            return tiles
                .map((tile) => {
                    const node = ko.unwrap(
                        tile.data[self.fileViewer.fileListNodeId]
                    );
                    if (
                        !node?.length ||
                        ko.unwrap(node[0].renderer) !== self.renderer
                    )
                        return null;
                    const configId = ko.unwrap(node[0].rendererConfig);
                    const cfg = configs.find(
                        (c) => c.configid === configId
                    );
                    const overrides = parseOverrides(ko.unwrap(node[0].parsingOverrides));
                    return {
                        name: ko.unwrap(node[0].name) || 'Unknown',
                        hasConfig: !!configId,
                        configName: cfg?.name || null,
                        configId: configId,
                        configObj: cfg?.config || {},
                        tileid: tile.tileid,
                        tile: tile,
                        node: node,
                        url: ko.unwrap(node[0].url),
                        hasOverrides: Object.keys(overrides).length > 0,
                        overrides: overrides,
                    };
                })
                .filter(Boolean);
        });

        // --- Per-file overrides in Status tab ---
        this.statusSelectedFiles = ko.observableArray([]);
        this.showOverridePanel = ko.observable(false);
        this.overrideDelimiterRadio = ko.observable('config');
        this.overrideDelimiterCustom = ko.observable('');
        this.overrideHeaderRadio = ko.observable('config');
        this.overrideHeader = ko.observable('');
        this.overrideFooterRadio = ko.observable('config');
        this.overrideFooter = ko.observable('');
        this.overrideSaving = ko.observable(false);

        // Dynamic label for button + panel title
        this.overrideTargetLabel = ko.pureComputed(() => {
            const files = self.statusSelectedFiles();
            if (files.length === 0) return '';
            if (files.length === 1) return files[0].name;
            return files.length + ' files';
        });

        // Read overrides live from node data (not cached snapshot)
        // After tile.save(), koMapping.fromJS() wraps nested props as observables,
        // so we use ko.toJS() to deeply unwrap all nested observables.
        const getFileOverrides = (file) => {
            return parseOverrides(ko.unwrap(file.node?.[0]?.parsingOverrides));
        };

        // Load radio state from a file's existing overrides
        const loadOverridesFromFile = (file) => {
            const ov = getFileOverrides(file);
            // Delimiter
            if (!ov.delimiterCharacter) {
                self.overrideDelimiterRadio('config');
                self.overrideDelimiterCustom('');
            } else if (ov.delimiterCharacter === 'auto') {
                self.overrideDelimiterRadio('auto');
                self.overrideDelimiterCustom('');
            } else if (ov.delimiterCharacter === ',') {
                self.overrideDelimiterRadio(',');
            } else if (ov.delimiterCharacter === '\t') {
                self.overrideDelimiterRadio('tab');
            } else {
                self.overrideDelimiterRadio('other');
                self.overrideDelimiterCustom(ov.delimiterCharacter);
            }
            // Header
            if (!ov.headerFixedLines) {
                self.overrideHeaderRadio('config');
                self.overrideHeader('');
            } else if (ov.headerFixedLines === 'auto') {
                self.overrideHeaderRadio('auto');
                self.overrideHeader('');
            } else {
                self.overrideHeaderRadio('fixed');
                self.overrideHeader(ov.headerFixedLines);
            }
            // Footer
            if (!ov.footerDelimiter) {
                self.overrideFooterRadio('config');
                self.overrideFooter('');
            } else if (ov.footerDelimiter === 'none') {
                self.overrideFooterRadio('none');
                self.overrideFooter('');
            } else {
                self.overrideFooterRadio('delimited');
                self.overrideFooter(ov.footerDelimiter);
            }
        };

        const resetOverrideRadios = () => {
            self.overrideDelimiterRadio('config');
            self.overrideDelimiterCustom('');
            self.overrideHeaderRadio('config');
            self.overrideHeader('');
            self.overrideFooterRadio('config');
            self.overrideFooter('');
        };

        // React to selection changes (checkbox or row click)
        this.disposables.push(this.statusSelectedFiles.subscribe((files) => {
            if (files.length === 1) {
                loadOverridesFromFile(files[0]);
            } else {
                resetOverrideRadios();
            }
        }));

        this.toggleStatusFile = (file) => {
            const idx = self.statusSelectedFiles.indexOf(file);
            if (idx > -1) {
                self.statusSelectedFiles.splice(idx, 1);
            } else {
                self.statusSelectedFiles.push(file);
            }
        };

        this.statusSelectAll = () => {
            self.statusSelectedFiles(self.allXyFiles().slice());
        };

        this.statusDeselectAll = () => {
            self.statusSelectedFiles([]);
            self.showOverridePanel(false);
        };

        this.overridePlaceholder = ko.pureComputed(() => {
            const files = self.statusSelectedFiles();
            if (files.length === 1) {
                const cfg = files[0].configObj || {};
                return {
                    delimiter: cfg.delimiterCharacter
                        ? '(' + cfg.delimiterCharacter + ')'
                        : '(auto)',
                    header: cfg.headerFixedLines
                        ? '(' + cfg.headerFixedLines + ' lines)'
                        : '(auto)',
                    footer: cfg.footerDelimiter
                        ? '(' + cfg.footerDelimiter + ')'
                        : '(none)',
                };
            }
            return { delimiter: '', header: '', footer: '' };
        });

        this.hasOverrideValues = ko.pureComputed(() => {
            return self.overrideDelimiterRadio() !== 'config' ||
                   self.overrideHeaderRadio() !== 'config' ||
                   self.overrideFooterRadio() !== 'config';
        });

        this.clearOverrides = () => {
            resetOverrideRadios();
        };

        // Build the overrides object from radio state
        const buildOverrides = () => {
            const overrides = {};
            const delRadio = self.overrideDelimiterRadio();
            if (delRadio === 'auto') {
                overrides.delimiterCharacter = 'auto';
            } else if (delRadio === ',') {
                overrides.delimiterCharacter = ',';
            } else if (delRadio === 'tab') {
                overrides.delimiterCharacter = '\t';
            } else if (delRadio === 'other' && self.overrideDelimiterCustom()) {
                overrides.delimiterCharacter = self.overrideDelimiterCustom();
            }
            // 'config' = don't override, key not set

            if (self.overrideHeaderRadio() === 'auto') {
                overrides.headerFixedLines = 'auto';
            } else if (self.overrideHeaderRadio() === 'fixed' && self.overrideHeader()) {
                overrides.headerFixedLines = self.overrideHeader();
            }
            // 'config' = don't override, key not set

            if (self.overrideFooterRadio() === 'none') {
                overrides.footerDelimiter = 'none';
            } else if (self.overrideFooterRadio() === 'delimited' && self.overrideFooter()) {
                overrides.footerDelimiter = self.overrideFooter();
            }
            // 'config' = don't override, key not set

            return Object.keys(overrides).length > 0 ? overrides : undefined;
        };

        this.saveOverrides = async () => {
            const files = self.statusSelectedFiles();
            if (!files.length) return;
            self.overrideSaving(true);

            const value = buildOverrides();

            for (const file of files) {
                try {
                    if (value) {
                        file.node[0].parsingOverrides = value;
                    } else {
                        delete file.node[0].parsingOverrides;
                    }
                    await file.tile.save();
                } catch (e) {
                    console.error('Override save error:', file.name, e);
                }
            }

            self.overrideSaving(false);
            self.showOverridePanel(false);
            self.statusSelectedFiles([]);
            self.render();
        };

        this.onConfigSaved = async () => {
            await rendererConfigRefresh();
            if (self.selectedConfig()) {
                self.selectedConfiguration = self.rendererConfigs().find(
                    (c) => c.configid === self.selectedConfig()
                );
                const display = self.selectedConfiguration?.config?.display;
                self._xRangeMin = display?.xRangeMin;
                self._xRangeMax = display?.xRangeMax;
                self._columnAssignments = display?.columnAssignments || null;
                self.yAxisRightLabel(display?.yAxisRightLabel || '');
                self.render();
                self.chartTitle(
                    display?.chartTitle
                        ? display.chartTitle
                        : arches.translations.data
                );
                self.xAxisLabel(
                    display?.xAxisLabel
                        ? display.xAxisLabel
                        : arches.translations.xAxis
                );
                self.yAxisLabel(
                    display?.yAxisLabel
                        ? display.yAxisLabel
                        : arches.translations.yAxis
                );
            }
        };

        this.disposables.push(this.delimiterCharacter.subscribe(() => {
            try {
                if (this.delimiterCharacter().length < 2) {
                    new RegExp(`[${this.delimiterCharacter()}\\s]+`);
                } else {
                    new RegExp(`${this.delimiterCharacter()}`);
                }
                this.invalidDelimiter(false);
            } catch {
                this.invalidDelimiter(true);
            }
        }));

        this.addConfiguration = () => {
            self.showConfigAdd(true);
        };

        this.saveConfiguration = async () => {
            const newConfiguration = {
                name: self.configName(),
                headerDelimiter: self.headerDelimiter(),
                headerFixedLines: self.headerFixedLines(),
                delimiterCharacter: self.delimiterCharacter(),
                rendererId: self.renderer,
            };
            const configSaveResponse = await fetch(
                arches.urls.renderer_config,
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
                invalidate(self.renderer);
                rendererConfigRefresh();
            }
            self.showConfigAdd(false);
        };

        // Track computed observables for disposal
        this.disposables.push(
            this.stagedXyTileCount,
            this.batchMode,
            this.canApplyBatch,
            this.stagedXyFiles,
            this.allXyFiles,
            this.overrideTargetLabel,
            this.overridePlaceholder,
            this.hasOverrideValues
        );

        this.dispose = () => {
            dispose(self);
        };

        this.parse = (text, series) => {
            // Read overrides from tile data (where they're actually stored),
            // same path as rendererConfigRefresh reads rendererConfig.
            let fileOverrides = {};
            const dc = self.fileViewer?.displayContent() || self.displayContent;
            if (dc?.tile) {
                const node = ko.unwrap(dc.tile.data[self.fileViewer.fileListNodeId]);
                fileOverrides = parseOverrides(ko.unwrap(node?.[0]?.parsingOverrides));
            }
            const baseConfig = this.selectedConfiguration?.config || {};
            const effectiveConfig = { ...baseConfig, ...fileOverrides };

            const validation = XyParser.validateContent(text);
            if (!validation.valid) {
                this.invalidDelimiter(true);
                throw new Error('Validation: ' + validation.error);
            }

            try {
                const parsedData = XyParser.parse(text, effectiveConfig);
                this.invalidDelimiter(false);
                const assignments = this._columnAssignments;
                const xMin = this._xRangeMin;
                const xMax = this._xRangeMax;

                if (parsedData.ys) {
                    if (assignments && assignments.length > 0) {
                        const leftSeries = [];
                        const rightSeries = [];
                        parsedData.ys.forEach((yArr, i) => {
                            const colAssign = assignments.find(
                                (a) => a.columnIndex === i + 1
                            );
                            const role = colAssign ? colAssign.role : 'yLeft';
                            if (role === 'yRight') {
                                rightSeries.push({
                                    value: [...parsedData.x],
                                    count: yArr,
                                    name: parsedData.seriesNames[i],
                                });
                            } else if (role !== 'ignore') {
                                leftSeries.push({
                                    value: [...parsedData.x],
                                    count: yArr,
                                    name: parsedData.seriesNames[i],
                                });
                            }
                        });
                        series.multiSeries = [...leftSeries, ...rightSeries];
                        series._rightAxisStartIndex = leftSeries.length;
                        if (leftSeries.length > 0) {
                            series.value.push(...leftSeries[0].value);
                            series.count.push(...leftSeries[0].count);
                        }
                    } else {
                        series.value.push(...parsedData.x);
                        series.count.push(...parsedData.ys[0]);
                        series.multiSeries = parsedData.ys.map((yArr, i) => ({
                            value: [...parsedData.x],
                            count: yArr,
                            name: parsedData.seriesNames[i],
                        }));
                    }
                } else {
                    series.value.push(...parsedData.x);
                    series.count.push(...parsedData.y);
                }

                // Apply spectral range filter
                if (xMin !== undefined || xMax !== undefined) {
                    const filtered = XyParser.filterXRange(
                        series.value,
                        series.count,
                        xMin,
                        xMax
                    );
                    series.value.length = 0;
                    series.count.length = 0;
                    series.value.push(...filtered.x);
                    series.count.push(...filtered.y);
                    if (series.multiSeries) {
                        series.multiSeries = series.multiSeries.map((s) => {
                            const f = XyParser.filterXRange(
                                s.value,
                                s.count,
                                xMin,
                                xMax
                            );
                            return { ...s, value: f.x, count: f.y };
                        });
                    }
                }
            } catch (e) {
                this.invalidDelimiter(true);
                throw e;
            }
        };
    },
    template: afsReaderTemplate,
});