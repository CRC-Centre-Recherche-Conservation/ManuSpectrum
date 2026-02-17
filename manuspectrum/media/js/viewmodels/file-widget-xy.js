import ko from 'knockout';
import $ from 'jquery';
import arches from 'arches';
import FileWidgetViewModel from 'viewmodels/file-widget';
import XyParser from 'utils/xy-parser';

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
var nodeChartRegistries = {};

function getOrCreateRegistry(nodeId) {
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
            labelsSet: false
        };
    }
    return nodeChartRegistries[nodeId];
}

/**
 * Extends FileWidgetViewModel with unified XY chart rendering in report mode.
 * Each tile's widget registers its files into a shared registry. Only the
 * first instance ("chart host") renders the Plotly chart; others contribute
 * data silently.
 */
var FileWidgetXYViewModel = function (params) {
    var self = this;

    FileWidgetViewModel.apply(this, [params]);

    this.reportXYFiles = ko.computed(function () {
        return self.uploadedFiles().filter(function (file) {
            var renderer = ko.unwrap(file.renderer);
            var rendererConfig = ko.unwrap(file.rendererConfig);
            return renderer === XY_RENDERER_UUID && !!rendererConfig;
        });
    });

    var nodeId = params.node ? params.node.nodeid : null;
    var registry = nodeId ? getOrCreateRegistry(nodeId) : null;

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

    // Dropdown
    this.dropdownOpen = ko.observable(false);

    this.showFileDropdown = ko.computed(function () {
        return self.xyFileEntries().length > 1;
    });

    this.selectedCount = ko.computed(function () {
        return self.xyFileEntries().filter(function (e) {
            return e.selected();
        }).length;
    });

    this.allLoading = ko.computed(function () {
        var entries = self.xyFileEntries();
        return (
            entries.length > 0 &&
            entries.every(function (e) {
                return e.loading();
            })
        );
    });

    this.hasChartData = ko.computed(function () {
        return self.xyFileEntries().some(function (e) {
            return e.chartData() !== null;
        });
    });

    this.noFilesSelected = ko.computed(function () {
        if (self.xyFileEntries().length === 0 || self.allLoading())
            return false;
        return self.selectedCount() === 0;
    });

    this.anyError = ko.computed(function () {
        return self.xyFileEntries().some(function (e) {
            return e.error() && !e.loading();
        });
    });

    // Unified Plotly traces
    this.unifiedChartData = ko.computed(function () {
        var allTraces = [];

        self.xyFileEntries().forEach(function (entry) {
            if (!entry.selected() || !entry.chartData()) return;

            var color = FILE_COLORS[entry.colorIndex % FILE_COLORS.length];
            var data = entry.chartData();

            if (data.series && Array.isArray(data.series)) {
                data.series.forEach(function (s, i) {
                    allTraces.push({
                        x: s.value,
                        y: s.count,
                        type: 'scatter',
                        mode: 'lines',
                        name: entry.fileName + ' - ' + s.name,
                        line: {
                            color: color,
                            width: 2,
                            dash: DASH_STYLES[i % DASH_STYLES.length]
                        }
                    });
                });
            } else {
                allTraces.push({
                    x: data.value,
                    y: data.count,
                    type: 'scatter',
                    mode: 'lines',
                    name: entry.fileName,
                    line: { color: color, width: 2 }
                });
            }
        });

        return allTraces;
    });

    // Dropdown actions
    this.toggleDropdown = function () {
        self.dropdownOpen(!self.dropdownOpen());
    };
    this.toggleFileSelection = function (entry) {
        entry.selected(!entry.selected());
    };
    this.selectAll = function () {
        self.xyFileEntries().forEach(function (e) {
            e.selected(true);
        });
    };
    this.deselectAll = function () {
        self.xyFileEntries().forEach(function (e) {
            e.selected(false);
        });
    };
    this.getFileColor = function (colorIndex) {
        return FILE_COLORS[colorIndex % FILE_COLORS.length];
    };

    this._closeDropdown = function (e) {
        if (
            self.dropdownOpen() &&
            !$(e.target).closest('.xy-file-dropdown').length
        ) {
            self.dropdownOpen(false);
        }
    };

    // Register this widget's XY files into the shared registry
    this._registerFiles = function () {
        var xyFiles = self.reportXYFiles();
        if (xyFiles.length === 0 || !registry) return;

        var currentCount = registry.entries().length;

        xyFiles.forEach(function (file, index) {
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
        var all = registry.entries();
        self._loadEntryData(all.slice(all.length - xyFiles.length));
    };

    // Fetch renderer config, download files, parse XY data
    this._loadEntryData = function (entries) {
        fetch('/renderer/' + XY_RENDERER_UUID)
            .then(function (res) {
                if (!res.ok) throw new Error('Renderer fetch failed');
                return res.json();
            })
            .then(function (rendererData) {
                var configMap = {};
                (rendererData.configs || []).forEach(function (cfg) {
                    configMap[cfg.configid] = cfg;
                });

                return Promise.all(
                    entries.map(function (entry) {
                        var configId = ko.unwrap(entry.file.rendererConfig);
                        var config = configMap[configId];

                        if (!config) {
                            entry.error('Configuration not found');
                            entry.loading(false);
                            return null;
                        }

                        if (!registry.labelsSet) {
                            var d = config.config && config.config.display;
                            if (d) {
                                registry.labelsSet = true;
                                if (d.chartTitle)
                                    registry.chartTitle(d.chartTitle);
                                if (d.xAxisLabel)
                                    registry.chartXAxisLabel(d.xAxisLabel);
                                if (d.yAxisLabel)
                                    registry.chartYAxisLabel(d.yAxisLabel);
                            }
                        }

                        return $.ajax({
                            url: entry._widget.getFileUrl(entry.file.url),
                            dataType: 'text'
                        })
                            .then(function (text) {
                                return { entry: entry, text: text, config: config };
                            })
                            .catch(function () {
                                entry.error('Unable to load file data');
                                entry.loading(false);
                                return null;
                            });
                    })
                );
            })
            .then(function (results) {
                results.forEach(function (r) {
                    if (!r) return;
                    try {
                        var parsed = XyParser.parse(r.text, r.config.config);

                        r.entry.chartData(
                            parsed.ys
                                ? {
                                      series: parsed.ys.map(function (y, i) {
                                          return {
                                              value: parsed.x,
                                              count: y,
                                              name: parsed.seriesNames[i]
                                          };
                                      })
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
            .catch(function (err) {
                console.error('XY chart init failed:', err);
                entries.forEach(function (entry) {
                    if (entry.loading()) {
                        entry.error('Unable to load chart configuration');
                        entry.loading(false);
                    }
                });
            });
    };

    // Cleanup on SPA navigation
    this.dispose = function () {
        if (!registry) return;

        registry.entries(
            registry.entries().filter(function (e) {
                return e._widget !== self;
            })
        );

        if (self.isChartHost()) {
            $(document).off('click.xyDropdown', self._closeDropdown);
            registry.hostWidget = null;
        }

        if (registry.entries().length === 0) {
            registry.labelsSet = false;
            delete nodeChartRegistries[nodeId];
        }
    };

    // Init
    if (params.state === 'report') {
        if (this.reportXYFiles().length > 0) {
            this._registerFiles();
        } else {
            var sub = this.reportXYFiles.subscribe(function (files) {
                if (files.length > 0) {
                    sub.dispose();
                    self._registerFiles();
                }
            });
        }
    }
};

export default FileWidgetXYViewModel;
