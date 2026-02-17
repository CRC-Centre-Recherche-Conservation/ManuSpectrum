import ko from 'knockout';
import $ from 'jquery';
import arches from 'arches';
import FileWidgetViewModel from 'viewmodels/file-widget';
import XyParser from 'utils/xy-parser';

const XY_RENDERER_UUID = 'e93b7b27-40d8-4141-996e-e59ff08742f3';

/**
 * Extends FileWidgetViewModel with XY chart rendering in report mode.
 * Adds reportXYFiles and xyCharts observables.
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

    this.xyCharts = ko.observableArray([]);

    this._initXYCharts = function () {
        var xyFiles = self.reportXYFiles();

        var chartEntries = xyFiles.map(function (file) {
            return {
                file: file,
                chartData: ko.observable(null),
                title: ko.observable(arches.translations.data || 'Data'),
                titleSize: ko.observable(24),
                xAxisLabel: ko.observable(
                    arches.translations.xAxis || 'X'
                ),
                xAxisLabelSize: ko.observable(17),
                yAxisLabel: ko.observable(
                    arches.translations.yAxis || 'Y'
                ),
                yAxisLabelSize: ko.observable(17),
                seriesStyles: ko.observableArray([]),
                seriesData: ko.observableArray([]),
                primarySeriesColor: '#3333ff',
                loading: ko.observable(true),
                error: ko.observable(null),
            };
        });
        self.xyCharts(chartEntries);

        fetch('/renderer/' + XY_RENDERER_UUID)
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('Failed to fetch renderer configs');
                }
                return response.json();
            })
            .then(function (rendererData) {
                var configMap = {};
                var configs = rendererData.configs || [];
                configs.forEach(function (cfg) {
                    configMap[cfg.configid] = cfg;
                });

                var fetchPromises = chartEntries.map(function (entry) {
                    var file = entry.file;
                    var configId = ko.unwrap(file.rendererConfig);
                    var config = configMap[configId];

                    if (!config) {
                        entry.error('Configuration not found');
                        entry.loading(false);
                        return Promise.resolve(null);
                    }

                    var display = config.config && config.config.display;
                    if (display) {
                        if (display.chartTitle)
                            entry.title(display.chartTitle);
                        if (display.xAxisLabel)
                            entry.xAxisLabel(display.xAxisLabel);
                        if (display.yAxisLabel)
                            entry.yAxisLabel(display.yAxisLabel);
                    }

                    var fileUrl = self.getFileUrl(file.url);

                    return $.ajax({
                        url: fileUrl,
                        dataType: 'text',
                    })
                        .then(function (text) {
                            return {
                                entry: entry,
                                text: text,
                                config: config,
                            };
                        })
                        .catch(function () {
                            entry.error('Unable to load file data');
                            entry.loading(false);
                            return null;
                        });
                });

                return Promise.all(fetchPromises);
            })
            .then(function (results) {
                results.forEach(function (result) {
                    if (!result) return;

                    var entry = result.entry;
                    var text = result.text;
                    var config = result.config;

                    try {
                        var parsedData = XyParser.parse(
                            text,
                            config.config
                        );
                        var chartData;

                        if (parsedData.ys) {
                            chartData = {
                                series: parsedData.ys.map(function (
                                    yArr,
                                    i
                                ) {
                                    return {
                                        value: parsedData.x,
                                        count: yArr,
                                        name: parsedData.seriesNames[i],
                                    };
                                }),
                            };
                        } else {
                            chartData = {
                                value: parsedData.x,
                                count: parsedData.y,
                                name: ko.unwrap(entry.file.name),
                            };
                        }

                        entry.chartData(chartData);
                    } catch (e) {
                        console.error(
                            'XY parse error for file:',
                            ko.unwrap(entry.file.name),
                            e
                        );
                        entry.error('Unable to parse file data');
                    }

                    entry.loading(false);
                });
            })
            .catch(function (err) {
                console.error('Failed to initialize XY charts:', err);
                chartEntries.forEach(function (entry) {
                    if (entry.loading()) {
                        entry.error('Unable to load chart configuration');
                        entry.loading(false);
                    }
                });
            });
    };

    if (params.state === 'report' && this.reportXYFiles().length > 0) {
        this._initXYCharts();
    }
};

export default FileWidgetXYViewModel;
