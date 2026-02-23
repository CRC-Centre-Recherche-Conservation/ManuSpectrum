import $ from 'jquery';
import _ from 'underscore';
import ko from 'knockout';
import 'knockout-mapping';
import 'bindings/plotly';

/**
* A viewmodel used for generic AFS instrument files
*
* @constructor
* @name AfsInstrumentViewModel
*
* @param  {string} params - a configuration object
*/
const AfsInstrumentViewModel = function(params) {
    this.params = params;
    this.fileType = 'text/plain';
    this.url = "";
    this.type = "";
    this.loading = ko.observable(true);
    this.commonData = params.state;
    this.fileViewer = params.fileViewer;
    this.displayContent = ko.unwrap(this.params.displayContent);
    const localStore = window.localStorage;

    const renderer = this.displayContent.renderer.id;
    this.renderer = renderer;
    const formatDefaults = {
        'title': localStore.getItem(renderer + 'title') || '',
        'titlesize': localStore.getItem(renderer + 'titlesize') || 24,
        'xaxislabel': localStore.getItem(renderer + 'xaxislabel') || "",
        'xaxislabelsize': localStore.getItem(renderer + 'xaxislabelsize') || 17,
        'yaxislabel': localStore.getItem(renderer + 'yaxislabel') || "",
        'yaxislabelsize': localStore.getItem(renderer + 'yaxislabelsize') || 17,
    };

    if ('chartData' in params.state === false) {
        this.commonData.chartData = ko.observable();
        this.commonData.seriesData = ko.observableArray([]);
        this.commonData.seriesStyles = ko.observableArray([]);
    }

    if ('chartTitle' in params.state === false) {
        this.commonData.chartTitle = ko.observable(formatDefaults['title']);
        this.commonData.titleSize = ko.observable(formatDefaults['titlesize']);
        this.commonData.xAxisLabel = ko.observable(formatDefaults['xaxislabel']);
        this.commonData.xAxisLabelSize = ko.observable(formatDefaults['xaxislabelsize']);
        this.commonData.yAxisLabel = ko.observable(formatDefaults['yaxislabel']);
        this.commonData.yAxisLabelSize = ko.observable(formatDefaults['yaxislabelsize']);
    }

    this.parsedData = this.commonData.parsedData;
    this.chartData = this.commonData.chartData;
    this.chartTitle = this.commonData.chartTitle;
    this.titleSize = this.commonData.titleSize;
    this.xAxisLabel = this.commonData.xAxisLabel;
    this.xAxisLabelSize = this.commonData.xAxisLabelSize;
    this.yAxisLabel = this.commonData.yAxisLabel;
    this.yAxisLabelSize = this.commonData.yAxisLabelSize;
    this.seriesData = this.commonData.seriesData;
    this.seriesStyles = this.commonData.seriesStyles;
    this.primarySeriesColor = this.fileViewer ? JSON.parse(localStore.getItem(renderer + 'series' + this.fileViewer.tile.tileid))?.color : "#3333ff";

    const chartFormattingDetails = {
        'title': this.chartTitle,
        'titlesize': this.titleSize,
        'xaxislabel': this.xAxisLabel,
        'xaxislabelsize': this.xAxisLabelSize,
        'yaxislabel': this.yAxisLabel,
        'yaxislabelsize': this.yAxisLabelSize
    };

    _.each(chartFormattingDetails, (val, key) => {
        const sub = val.subscribe((val) => {
            localStore.setItem(renderer + key, val);
        });
        if (this.disposables) {
            this.disposables.push(sub);
        }
    });

    this.render = () => {
        const series = {
            'value': [],
            'count': [],
            'name': this.displayContent.name
        };
        $.ajax({
            url: this.displayContent.url,
            dataType: "text"})
            .done((data) => {
                this.displayContent.validRenderer(true);
                try {
                    this.parse(data, series);
                    // clear the data before you add new data, this fixes a bug in the
                    // afs file-interpretation step where data wouldn't be updated until
                    // the file was selected a second time
                    this.chartData(undefined);

                    if (series.multiSeries && series.multiSeries.length > 1) {
                        this.chartData({
                            series: series.multiSeries.map((s) => ({
                                value: s.value,
                                count: s.count,
                                name: this.displayContent.name + ' - ' + s.name
                            }))
                        });
                    } else {
                        this.chartData(series);
                    }

                    if (!this.fileViewer) {
                        if (series.count.length === 0) {
                            this.displayContent.validRenderer(false);
                        }
                        if (series.multiSeries && series.multiSeries.length > 1) {
                            series.multiSeries.forEach((s) => {
                                this.seriesData.push({
                                    data: s,
                                    name: this.displayContent.name + ' - ' + s.name
                                });
                            });
                        } else {
                            this.seriesData.push({data: series, name: this.displayContent.name});
                        }
                    }
                } catch {
                    this.displayContent.validRenderer(false);
                }
                this.loading(false);
                this.displayContent.validRenderer.valueHasMutated();
            });
    };

    this.chartOptions = {
        axis: {
            x: {
                tick: {
                    count: 5
                }
            }
        },
        zoom: {
            enabled: true
        },
    };

    if (this.displayContent) {
        this.url = this.displayContent.url;
        this.type = this.displayContent.type;
        if (this.params.context === 'render') {
            this.render();
        } else if (this.params.context === 'parse'){
            this.render();
        }
    }

};

export default AfsInstrumentViewModel;
