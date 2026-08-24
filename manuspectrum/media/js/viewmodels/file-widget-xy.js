import ko from 'knockout';
import $ from 'jquery';
import arches from 'arches';
import FileWidgetViewModel from 'viewmodels/file-widget';
import XyParser from 'utils/xy-parser';
import {
    applyTransforms,
    deriveAxisLabel,
    describeChain,
    expandStoredConfig,
} from 'utils/xy-transforms';
import { BASE_VIEW, findView, viewsFor } from 'utils/xy-views';
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
            // What the configuration applied, stated under the chart. Null
            // renders as "none" rather than as nothing at all.
            processing: ko.observable(null),
            // The reader's lens. Always opens on the base quantity: a
            // remembered default would read as "the official view".
            selectedView: ko.observable(BASE_VIEW),
            // Kept apart from chartYAxisLabel, which already carries the view's
            // annotation — this is the quantity the configuration produced.
            baseYAxisLabel: ko.observable(''),
            storedConfig: ko.observable(null),
            // Descending X axis, as FTIR, NMR and XPS are conventionally plotted.
            chartXReversed: ko.observable(false),
            xRangeMin: ko.observable(undefined),
            xRangeMax: ko.observable(undefined),
            columnAssignments: null,
            xColumnMode: null,
            xColumnIndex: 0,
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
    this.chartXReversed = registry
        ? registry.chartXReversed
        : ko.observable(false);
    this.processing = registry ? registry.processing : ko.observable(null);
    this.selectedView = registry
        ? registry.selectedView
        : ko.observable(BASE_VIEW);
    this.storedConfig = registry ? registry.storedConfig : ko.observable(null);

    // The lenses this instrument family supports. A hand-made configuration
    // carries no preset key and so offers the base quantity alone.
    // Labels resolved here rather than in the binding: the template has no
    // reliable access to this project's translation bundle.
    const VIEW_LABELS = {
        base: 'xyViewBase',
        'log-inverse-r': 'xyViewLogInverseR',
        'kubelka-munk': 'xyViewKubelkaMunk',
        'normalize-max': 'xyViewNormalizeMax',
        'normalize-area': 'xyViewNormalizeArea',
        'derivative-1': 'xyViewDerivative1',
        'derivative-2': 'xyViewDerivative2',
    };
    this.availableViews = ko.pureComputed(() =>
        viewsFor(self.storedConfig()).map((v) => ({
            ...v,
            label: arches.translations[VIEW_LABELS[v.key]] || v.key,
        }))
    );
    this.showViewControl = ko.pureComputed(
        () => self.availableViews().length > 1
    );
    this.currentView = ko.pureComputed(() =>
        findView(self.storedConfig(), self.selectedView())
    );

    // The axis keeps naming the measured quantity and gains a bracket saying
    // how it is being shown — "Reflectance (%) [log10(1/R)]", never "log10(1/R)"
    // alone. The reader must not lose the reference point.
    this.displayYAxisLabel = ko.pureComputed(() =>
        deriveAxisLabel(registry ? registry.baseYAxisLabel() : '', {
            transforms: self.currentView().transforms,
        })
    );

    // One line stating everything applied, configuration and lens alike. Reads
    // "none applied" when neither did anything: silence must not be
    // indistinguishable from an untouched spectrum.
    this.processingNote = ko.pureComputed(() => {
        const applied = [
            self.processing(),
            describeChain({ transforms: self.currentView().transforms }),
        ].filter(Boolean);
        return applied.length ? applied.join(' -> ') : null;
    });
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
        self.xyFileEntries().some((e) => e.chartData && e.chartData() !== null)
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
        const xColIdx = registry ? parseInt(registry.xColumnIndex ?? 0, 10) : 0;

        self.xyFileEntries().forEach((entry) => {
            if (!entry.selected() || !entry.chartData || !entry.chartData())
                return;

            const color = FILE_COLORS[entry.colorIndex % FILE_COLORS.length];
            const data = entry.chartData();

            if (data.series && Array.isArray(data.series)) {
                data.series.forEach((s, i) => {
                    // Map series index back to original file column index
                    const colIdx = isGenerate ? i : (i < xColIdx ? i : i + 1);
                    const colAssign = assignments
                        ? assignments.find((a) => a.columnIndex === colIdx)
                        : null;
                    if (colAssign && colAssign.role === 'ignore') return;

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
                    if (colAssign && colAssign.role === 'yRight') {
                        trace.yaxis = 'y2';
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
            const entry = {
                file: file,
                fileName:
                    ko.unwrap(file.name) ||
                    'File ' + (currentCount + index + 1),
                parsed: ko.observable(null),
                colorIndex: currentCount + index,
                selected: ko.observable(true),
                loading: ko.observable(true),
                error: ko.observable(null),
                _widget: self
            };

            // Derived rather than stored: the lens is applied on the way to the
            // chart, so changing it costs one pass over an already-parsed
            // spectrum instead of a fresh download and parse.
            //
            // Attached BEFORE the entry reaches the array: pushing notifies the
            // computeds watching it, and they call chartData() straight away.
            entry.chartData = ko.pureComputed(() => {
                const parsed = entry.parsed();
                if (!parsed) return null;
                const transforms = findView(
                    registry.storedConfig(),
                    registry.selectedView()
                ).transforms;
                const seen = transforms.length
                    ? applyTransforms(parsed, { transforms: transforms })
                    : parsed;
                return seen.ys
                    ? {
                          series: seen.ys.map((y, i) => ({
                              value: seen.x,
                              count: y,
                              name: seen.seriesNames[i],
                          })),
                      }
                    : {
                          value: seen.x,
                          count: seen.y,
                          name: entry.fileName,
                      };
            });

            registry.entries.push(entry);
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
                                    // Derived, never the stored string on its
                                    // own: the label must follow what is
                                    // actually plotted.
                                    registry.chartYAxisLabel(
                                        deriveAxisLabel(
                                            d.yAxisLabel,
                                            expandStoredConfig(config.config)
                                        )
                                    );
                                registry.processing(
                                    describeChain(
                                        expandStoredConfig(config.config)
                                    )
                                );
                                registry.baseYAxisLabel(d.yAxisLabel || '');
                                registry.storedConfig(config.config);
                                if (d.yAxisRightLabel)
                                    registry.chartYAxisRightLabel(
                                        d.yAxisRightLabel
                                    );
                                if (d.xRangeMin !== undefined)
                                    registry.xRangeMin(d.xRangeMin);
                                if (d.xRangeMax !== undefined)
                                    registry.xRangeMax(d.xRangeMax);
                                registry.chartXReversed(!!d.xReversed);
                                if (d.columnAssignments)
                                    registry.columnAssignments =
                                        d.columnAssignments;
                            }
                            if (config.config.xColumnMode)
                                registry.xColumnMode =
                                    config.config.xColumnMode;
                            if (config.config.xColumnIndex !== undefined)
                                registry.xColumnIndex =
                                    config.config.xColumnIndex;
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
                        const effectiveConfig = expandStoredConfig(
                            Object.assign({}, r.config.config, fileOverrides)
                        );

                        const validation = XyParser.validateContent(r.text, {
                            xColumnMode: effectiveConfig.xColumnMode,
                            xColumnIndex: effectiveConfig.xColumnIndex
                        });
                        if (!validation.valid) {
                            r.entry.error('Validation: ' + validation.error);
                            r.entry.loading(false);
                            return;
                        }

                        const parsed = applyTransforms(
                            XyParser.parse(r.text, effectiveConfig),
                            effectiveConfig
                        );

                        r.entry.parsed(parsed);
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
