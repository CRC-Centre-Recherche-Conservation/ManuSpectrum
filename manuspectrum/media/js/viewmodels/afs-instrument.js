define(['jquery',
    'underscore',
    'knockout',
    'knockout-mapping',
    'bindings/plotly'
], function($, _, ko) {
    /**
    * A viewmodel used for generic AFS instrument files
    *
    * @constructor
    * @name AfsInstrumentViewModel
    *
    * @param  {string} params - a configuration object
    */
    var AfsInstrumentViewModel = function(params) {
        var self = this;
        this.params = params;
        this.fileType = 'text/plain';
        this.url = "";
        this.type = "";
        this.loading = ko.observable(true);
        this.commonData = params.state;
        this.fileViewer = params.fileViewer;
        this.displayContent = ko.unwrap(this.params.displayContent);
        var localStore = window.localStorage;

        var renderer = this.displayContent.renderer.id;
        this.renderer = renderer;
        var formatDefaults = {
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

        var chartFormattingDetails = {
            'title': this.chartTitle,
            'titlesize': this.titleSize, 
            'xaxislabel': this.xAxisLabel,
            'xaxislabelsize': this.xAxisLabelSize,
            'yaxislabel': this.yAxisLabel,
            'yaxislabelsize': this.yAxisLabelSize
        };

        _.each(chartFormattingDetails, function(val, key) {
            var sub = val.subscribe(function(val){
                localStore.setItem(renderer + key, val);
            });
            if (self.disposables) {
                self.disposables.push(sub);
            }
        });

        this.render  = function() {
            var series = {
                'value': [],
                'count': [],
                'name': this.displayContent.name
            };
            $.ajax({
                url : this.displayContent.url,
                dataType: "text"})
                .done(function(data) {
                    self.displayContent.validRenderer(true);
                    try {
                        self.parse(data, series);
                        // clear the data before you add new data, this fixes a bug in the
                        // afs file-interpretation step where data wouldn't be updated until
                        // the file was selected a second time
                        self.chartData(undefined);

                        if (series.multiSeries && series.multiSeries.length > 1) {
                            self.chartData({
                                series: series.multiSeries.map(function(s) {
                                    return {
                                        value: s.value,
                                        count: s.count,
                                        name: self.displayContent.name + ' - ' + s.name
                                    };
                                })
                            });
                        } else {
                            self.chartData(series);
                        }

                        if (!self.fileViewer) {
                            if (series.count.length === 0) {
                                self.displayContent.validRenderer(false);
                            }
                            if (series.multiSeries && series.multiSeries.length > 1) {
                                series.multiSeries.forEach(function(s) {
                                    self.seriesData.push({
                                        data: s,
                                        name: self.displayContent.name + ' - ' + s.name
                                    });
                                });
                            } else {
                                self.seriesData.push({data: series, name: self.displayContent.name});
                            }
                        }
                    } catch(e) {
                        self.displayContent.validRenderer(false);
                    }
                    self.loading(false);
                    self.displayContent.validRenderer.valueHasMutated();
                }, this);
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
            if (self.params.context === 'render') {
                self.render();
            } else if (self.params.context === 'parse'){
                self.render();
            }
        }

    };

    return AfsInstrumentViewModel;
});