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

        // set defaults for chart title/axis
        this.chartTitle(arches.translations.data);
        this.xAxisLabel(arches.translations.xAxis);
        this.yAxisLabel(arches.translations.yAxis);

        this.rendererConfigs = ko.observable([]);

        // on init, get available renderer configs for display to user.
        const rendererConfigRefresh = async () => {
            const rendererResponse = await fetch(
                arches.urls.renderer(self.renderer)
            );
            if (rendererResponse.ok) {
                const renderers = await rendererResponse.json();
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
            }
        };

        this.selectedConfig.subscribe((config) => {
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
            this.chartTitle(
                this.selectedConfiguration?.config?.display?.chartTitle
                    ? this.selectedConfiguration.config.display.chartTitle
                    : arches.translations.data
            );
            this.xAxisLabel(
                this.selectedConfiguration?.config?.display?.xAxisLabel
                    ? this.selectedConfiguration.config.display.xAxisLabel
                    : arches.translations.xAxis
            );
            this.yAxisLabel(
                this.selectedConfiguration?.config?.display?.yAxisLabel
                    ? this.selectedConfiguration.config.display.yAxisLabel
                    : arches.translations.yAxis
            );
        });

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
                    return {
                        name: ko.unwrap(node[0].name) || 'Unknown',
                        hasConfig: !!configId,
                        configName: cfg?.name || null,
                        configId: configId,
                        tileid: tile.tileid,
                        url: ko.unwrap(node[0].url),
                    };
                })
                .filter(Boolean);
        });

        this.onConfigSaved = async () => {
            await rendererConfigRefresh();
            if (self.selectedConfig()) {
                self.selectedConfiguration = self.rendererConfigs().find(
                    (c) => c.configid === self.selectedConfig()
                );
                self.render();
                self.chartTitle(
                    self.selectedConfiguration?.config?.display?.chartTitle
                        ? self.selectedConfiguration.config.display.chartTitle
                        : arches.translations.data
                );
                self.xAxisLabel(
                    self.selectedConfiguration?.config?.display?.xAxisLabel
                        ? self.selectedConfiguration.config.display.xAxisLabel
                        : arches.translations.xAxis
                );
                self.yAxisLabel(
                    self.selectedConfiguration?.config?.display?.yAxisLabel
                        ? self.selectedConfiguration.config.display.yAxisLabel
                        : arches.translations.yAxis
                );
            }
        };

        this.delimiterCharacter.subscribe((x) => {
            try {
                const valueRegex =
                    this.delimiterCharacter().length < 2
                        ? new RegExp(`[${this.delimiterCharacter()}\\s]+`)
                        : new RegExp(`${this.delimiterCharacter()}`);
                this.invalidDelimiter(false);
            } catch {
                this.invalidDelimiter(true);
            }
        });

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
                rendererConfigRefresh();
            }
            self.showConfigAdd(false);
        };

        this.parse = function (text, series) {
            const fileOverrides = this.displayContent?.parsingOverrides || {};
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

                if (parsedData.ys) {
                    series.value.push(...parsedData.x);
                    series.count.push(...parsedData.ys[0]);
                    series.multiSeries = parsedData.ys.map((yArr, i) => ({
                        value: [...parsedData.x],
                        count: yArr,
                        name: parsedData.seriesNames[i]
                    }));
                } else {
                    series.value.push(...parsedData.x);
                    series.count.push(...parsedData.y);
                }
            } catch (e) {
                this.invalidDelimiter(true);
                throw e;
            }
        };
    },
    template: afsReaderTemplate,
});