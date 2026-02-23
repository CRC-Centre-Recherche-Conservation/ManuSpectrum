import ko from 'knockout';
import $ from 'jquery';
import arches from 'arches';
import FileWidgetViewModel from 'viewmodels/file-widget';
import XyParser from 'utils/xy-parser';
import dispose from 'utils/dispose';
import { getRendererConfig, parseOverrides } from 'utils/renderer-cache';

const XY_RENDERER_UUID = 'e93b7b27-40d8-4141-996e-e59ff08742f3';

const FILE_COLORS = [
    '#3333ff', '#ff6633', '#33cc33', '#cc33ff', '#ffcc00',
    '#00cccc', '#ff3366', '#6633ff', '#33ccff', '#ff9933'
];

const DASH_STYLES = ['solid', 'dash', 'dot', 'dashdot'];

/**
 * Module-level registry keyed by node ID. Groups XY file entries across
 * widget instances (one per tile) so they share a single Plotly chart.
 */
const nodeChartRegistries = {};

const getOrCreateRegistry = (nodeId) => {
    if (!nodeChartRegistries[nodeId]) {
        nodeChartRegistries[nodeId] = {
            entries: ko.observableArray([]),
            hostWidget: null,
            chartTitle: ko.observable(arches.translations.data || 'Data'),
            chartTitleSize: ko.observable(24),
            chartXAxisLabel: ko.observable(
                arches.translations.xAxis || 'X'
            ),
            chartXAxisLabelSize: ko.observable(17),
            chartYAxisLabel: ko.observable(
                arches.translations.yAxis || 'Y'
            ),
            chartYAxisLabelSize: ko.observable(17),
            chartYAxisRightLabel: ko.observable(''),
            xRangeMin: ko.observable(undefined),
            xRangeMax: ko.observable(undefined),
            columnAssignments: null,
            xColumnMode: null,
            labelsSet: false
        };
    }
    return nodeChartRegistries[nodeId];
};

/**
 * Extends FileWidgetViewModel with unified XY chart rendering in report mode.
 * Each tile's widget registers its files into a shared registry. Only the
 * first instance ("chart host") renders the Plotly chart; others contribute
 * data silently.
 */
const FileWidgetXYViewModel = function (params) {
    const self = this;

    FileWidgetViewModel.apply(this, [params]);

    this.reportXYFiles = ko.computed(() =>
        self.uploadedFiles().filter((file) => {
            const renderer = ko.unwrap(file.renderer);
            const rendererConfig = ko.unwrap(file.rendererConfig);
            return renderer === XY_RENDERER_UUID && !!rendererConfig;
        })
    );

    const nodeId = params.node ? params.node.nodeid : null;
    const registry = nodeId ? getOrCreateRegistry(nodeId) : null;

    this.isChartHost = ko.observable(false);
    if (registry && !registry.hostWidget) {
        registry.hostWidget = this;
        this.isChartHost(true);
    }

    this.xyFileEntries = registry
        ? registry.entries
        : ko.observableArray([]);
    this.chartTitle = registry ? registry.chartTitle : ko.observable('');
    this.chartTitleSize = registry
        ? registry.chartTitleSize
        : ko.observable(24);
    this.chartXAxisLabel = registry
        ? registry.chartXAxisLabel
        : ko.observable('');
    this.chartXAxisLabelSize = registry
        ? registry.chartXAxisLabelSize
        : ko.observable(17);
    this.chartYAxisLabel = registry
        ? registry.chartYAxisLabel
        : ko.observable('');
    this.chartYAxisLabelSize = registry
        ? registry.chartYAxisLabelSize
        : ko.observable(17);
    this.chartYAxisRightLabel = registry
        ? registry.chartYAxisRightLabel
        : ko.observable('');
    this.xRangeMin = registry
        ? registry.xRangeMin
        : ko.observable(undefined);
    this.xRangeMax = registry
        ? registry.xRangeMax
        : ko.observable(undefined);

    // Dropdown
    this.dropdownOpen = ko.observable(false);

    this.showFileDropdown = ko.computed(() =>
        self.xyFileEntries().length > 1
    );

    this.selectedCount = ko.computed(() =>
        self.xyFileEntries().filter((e) => e.selected()).length
    );

    this.allLoading = ko.computed(() => {
        const entries = self.xyFileEntries();
        return entries.length > 0 && entries.every((e) => e.loading());
    });

    this.hasChartData = ko.computed(() =>
        self.xyFileEntries().some((e) => e.chartData() !== null)
    );

    this.noFilesSelected = ko.computed(() => {
        if (self.xyFileEntries().length === 0 || self.allLoading())
            return false;
        return self.selectedCount() === 0;
    });

    this.anyError = ko.computed(() =>
        self.xyFileEntries().some((e) => e.error() && !e.loading())
    );

    // Unified Plotly traces
    this.unifiedChartData = ko.computed(() => {
        const allTraces = [];
        const xMin = self.xRangeMin();
        const xMax = self.xRangeMax();
        const assignments = registry ? registry.columnAssignments : null;
        const isGenerate = registry && registry.xColumnMode === 'generate';

        self.xyFileEntries().forEach((entry) => {
            if (!entry.selected() || !entry.chartData()) return;

            const color = FILE_COLORS[entry.colorIndex % FILE_COLORS.length];
            const data = entry.chartData();

            if (data.series && Array.isArray(data.series)) {
                data.series.forEach((s, i) => {
                    // In standard mode col 0 is X, so series i maps to col i+1
                    // In generate mode all cols are Y, so series i maps to col i
                    const colIdx = isGenerate ? i : i + 1;
                    if (assignments) {
                        const colAssign = assignments.find(
                            (a) => a.columnIndex === colIdx
                        );
                        if (colAssign && colAssign.role === 'ignore') return;
                    }

                    const filtered = XyParser.filterXRange(
                        s.value,
                        s.count,
                        xMin,
                        xMax
                    );
                    const trace = {
                        x: filtered.x,
                        y: filtered.y,
                        type: 'scatter',
                        mode: 'lines',
                        name: entry.fileName + ' - ' + s.name,
                        line: {
                            color: color,
                            width: 2,
                            dash: DASH_STYLES[i % DASH_STYLES.length],
                        },
                    };
                    if (assignments) {
                        const colAssign = assignments.find(
                            (a) => a.columnIndex === colIdx
                        );
                        if (colAssign && colAssign.role === 'yRight') {
                            trace.yaxis = 'y2';
                        }
                    }
                    allTraces.push(trace);
                });
            } else {
                const filtered = XyParser.filterXRange(
                    data.value,
                    data.count,
                    xMin,
                    xMax
                );
                allTraces.push({
                    x: filtered.x,
                    y: filtered.y,
                    type: 'scatter',
                    mode: 'lines',
                    name: entry.fileName,
                    line: { color: color, width: 2 },
                });
            }
        });

        return allTraces;
    });

    // Track computed observables for disposal
    this.disposables.push(
        this.reportXYFiles,
        this.showFileDropdown,
        this.selectedCount,
        this.allLoading,
        this.hasChartData,
        this.noFilesSelected,
        this.anyError,
        this.unifiedChartData
    );

    // Dropdown actions
    this.toggleDropdown = () => {
        self.dropdownOpen(!self.dropdownOpen());
    };
    this.toggleFileSelection = (entry) => {
        entry.selected(!entry.selected());
    };
    this.selectAll = () => {
        self.xyFileEntries().forEach((e) => {
            e.selected(true);
        });
    };
    this.deselectAll = () => {
        self.xyFileEntries().forEach((e) => {
            e.selected(false);
        });
    };
    this.getFileColor = (colorIndex) =>
        FILE_COLORS[colorIndex % FILE_COLORS.length];

    this._closeDropdown = (e) => {
        if (
            self.dropdownOpen() &&
            !$(e.target).closest('.xy-file-dropdown').length
        ) {
            self.dropdownOpen(false);
        }
    };

    // Register this widget's XY files into the shared registry
    this._registerFiles = () => {
        const xyFiles = self.reportXYFiles();
        if (xyFiles.length === 0 || !registry) return;

        const currentCount = registry.entries().length;

        xyFiles.forEach((file, index) => {
            registry.entries.push({
                file: file,
                fileName:
                    ko.unwrap(file.name) ||
                    'File ' + (currentCount + index + 1),
                chartData: ko.observable(null),
                colorIndex: currentCount + index,
                selected: ko.observable(true),
                loading: ko.observable(true),
                error: ko.observable(null),
                _widget: self
            });
        });

        if (self.isChartHost()) {
            $(document).on('click.xyDropdown', self._closeDropdown);
        }

        // Only load the entries this widget just added
        const all = registry.entries();
        self._loadEntryData(all.slice(all.length - xyFiles.length));
    };

    // Fetch renderer config, download files, parse XY data
    this._loadEntryData = (entries) => {
        getRendererConfig(XY_RENDERER_UUID)
            .then((rendererData) => {
                const configMap = {};
                (rendererData.configs || []).forEach((cfg) => {
                    configMap[cfg.configid] = cfg;
                });

                return Promise.all(
                    entries.map((entry) => {
                        const configId = ko.unwrap(entry.file.rendererConfig);
                        const config = configMap[configId];

                        if (!config) {
                            entry.error('Configuration not found');
                            entry.loading(false);
                            return null;
                        }

                        if (!registry.labelsSet) {
                            const d = config.config && config.config.display;
                            if (d) {
                                registry.labelsSet = true;
                                if (d.chartTitle)
                                    registry.chartTitle(d.chartTitle);
                                if (d.xAxisLabel)
                                    registry.chartXAxisLabel(d.xAxisLabel);
                                if (d.yAxisLabel)
                                    registry.chartYAxisLabel(d.yAxisLabel);
                                if (d.yAxisRightLabel)
                                    registry.chartYAxisRightLabel(
                                        d.yAxisRightLabel
                                    );
                                if (d.xRangeMin !== undefined)
                                    registry.xRangeMin(d.xRangeMin);
                                if (d.xRangeMax !== undefined)
                                    registry.xRangeMax(d.xRangeMax);
                                if (d.columnAssignments)
                                    registry.columnAssignments =
                                        d.columnAssignments;
                            }
                            if (config.config.xColumnMode)
                                registry.xColumnMode =
                                    config.config.xColumnMode;
                        }

                        return $.ajax({
                            url: entry._widget.getFileUrl(entry.file.url),
                            dataType: 'text'
                        })
                            .then((text) => ({ entry, text, config }))
                            .catch(() => {
                                entry.error('Unable to load file data');
                                entry.loading(false);
                                return null;
                            });
                    })
                );
            })
            .then((results) => {
                results.forEach((r) => {
                    if (!r) return;
                    try {
                        const fileOverrides = parseOverrides(ko.unwrap(r.entry.file.parsingOverrides));
                        const effectiveConfig = Object.assign({}, r.config.config, fileOverrides);

                        const validation = XyParser.validateContent(r.text, {
                            xColumnMode: effectiveConfig.xColumnMode
                        });
                        if (!validation.valid) {
                            r.entry.error('Validation: ' + validation.error);
                            r.entry.loading(false);
                            return;
                        }

                        const parsed = XyParser.parse(r.text, effectiveConfig);

                        r.entry.chartData(
                            parsed.ys
                                ? {
                                      series: parsed.ys.map((y, i) => ({
                                          value: parsed.x,
                                          count: y,
                                          name: parsed.seriesNames[i]
                                      }))
                                  }
                                : {
                                      value: parsed.x,
                                      count: parsed.y,
                                      name: r.entry.fileName
                                  }
                        );
                    } catch (e) {
                        console.error('XY parse error:', r.entry.fileName, e);
                        r.entry.error('Unable to parse file data');
                    }
                    r.entry.loading(false);
                });
            })
            .catch((err) => {
                console.error('XY chart init failed:', err);
                entries.forEach((entry) => {
                    if (entry.loading()) {
                        entry.error('Unable to load chart configuration');
                        entry.loading(false);
                    }
                });
            });
    };

    // Cleanup on SPA navigation
    this.dispose = () => {
        if (registry) {
            registry.entries(
                registry.entries().filter((e) => e._widget !== self)
            );

            if (self.isChartHost()) {
                $(document).off('click.xyDropdown', self._closeDropdown);
                registry.hostWidget = null;
            }

            if (registry.entries().length === 0) {
                registry.labelsSet = false;
                delete nodeChartRegistries[nodeId];
            }
        }

        dispose(self);
    };

    // Init
    if (params.state === 'report') {
        if (this.reportXYFiles().length > 0) {
            this._registerFiles();
        } else {
            const sub = this.reportXYFiles.subscribe((files) => {
                if (files.length > 0) {
                    sub.dispose();
                    self._registerFiles();
                }
            });
            this.disposables.push(sub);
        }
    }
};

export default FileWidgetXYViewModel;
