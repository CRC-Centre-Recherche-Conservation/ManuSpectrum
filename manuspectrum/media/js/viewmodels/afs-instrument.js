// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science

import $ from 'jquery';
import _ from 'underscore';
import ko from 'knockout';
import 'knockout-mapping';
import 'bindings/plotly';
import 'bindings/select2-query';

/**
 * A viewmodel used for generic AFS instrument files
 *
 * @constructor
 * @name AfsInstrumentViewModel
 *
 * @param {object} params - configuration object
 */
export default function AfsInstrumentViewModel(params) {
    const self = this;

    this.params = params;
    this.fileType = 'text/plain';
    this.url = '';
    this.type = '';
    this.loading = ko.observable(true);
    this.commonData = params.state;
    this.fileViewer = params.fileViewer;
    this.filter = ko.observable('');
    this.displayContent = ko.unwrap(this.params.displayContent);

    const localStore = window.localStorage;
    const renderer = this.displayContent.renderer.id;
    this.renderer = renderer;

    const formatDefaults = {
        title: localStore.getItem(renderer + 'title') || '',
        titlesize: localStore.getItem(renderer + 'titlesize') || 24,
        xaxislabel: localStore.getItem(renderer + 'xaxislabel') || '',
        xaxislabelsize: localStore.getItem(renderer + 'xaxislabelsize') || 17,
        yaxislabel: localStore.getItem(renderer + 'yaxislabel') || '',
        yaxislabelsize: localStore.getItem(renderer + 'yaxislabelsize') || 17
    };

    if (!('chartData' in params.state)) {
        this.commonData.chartData = ko.observable();
        this.commonData.seriesData = ko.observableArray([]);
        this.commonData.stagedSeries = ko.observableArray([]);
        this.commonData.seriesStyles = ko.observableArray([]);
        this.commonData.compatibleSeries = ko.pureComputed(() => {
            if (self.fileViewer) {
                return self.fileViewer.card.tiles()
                    .filter(tile =>
                        self.fileViewer.getUrl(tile).renderer &&
                        self.fileViewer.getUrl(tile).renderer.id ===
                            self.fileViewer.displayContent().renderer.id &&
                        self.fileViewer.selected().tileid !== tile.tileid
                    )
                    .map(t => ({
                        text: self.fileViewer.getUrl(t).name,
                        id: t.tileid
                    }));
            }
        });
    }

    if (!('chartTitle' in params.state)) {
        this.commonData.chartTitle = ko.observable(formatDefaults.title);
        this.commonData.titleSize = ko.observable(formatDefaults.titlesize);
        this.commonData.xAxisLabel = ko.observable(formatDefaults.xaxislabel);
        this.commonData.xAxisLabelSize = ko.observable(formatDefaults.xaxislabelsize);
        this.commonData.yAxisLabel = ko.observable(formatDefaults.yaxislabel);
        this.commonData.yAxisLabelSize = ko.observable(formatDefaults.yaxislabelsize);
        this.commonData.selectedSeriesTile = ko.observable(null);
        this.commonData.colorHolder = ko.observable('#ff00ff');
    }

    Object.assign(this, {
        parsedData: this.commonData.parsedData,
        chartData: this.commonData.chartData,
        chartTitle: this.commonData.chartTitle,
        titleSize: this.commonData.titleSize,
        xAxisLabel: this.commonData.xAxisLabel,
        xAxisLabelSize: this.commonData.xAxisLabelSize,
        yAxisLabel: this.commonData.yAxisLabel,
        yAxisLabelSize: this.commonData.yAxisLabelSize,
        seriesData: this.commonData.seriesData,
        stagedSeries: this.commonData.stagedSeries,
        selectedSeriesTile: this.commonData.selectedSeriesTile,
        seriesStyles: this.commonData.seriesStyles,
        colorHolder: this.commonData.colorHolder,
        compatibleSeries: this.commonData.compatibleSeries
    });

    this.primarySeriesColor = this.fileViewer
        ? JSON.parse(
              localStore.getItem(renderer + 'series' + this.fileViewer.tile.tileid)
          )?.color
        : '#3333ff';

    this.selectedSeriesTile.subscribe(tile => {
        if (tile) {
            const existing = self.seriesStyles().find(el => el.tileid === tile.tileid);
            if (existing) self.colorHolder(existing.color);
        }
    });

    this.colorHolder.subscribe(val => {
        if (!self.selectedSeriesTile() || !val) return;

        const tile = self.selectedSeriesTile();
        const existing = self.seriesStyles().find(el => el.tileid === tile.tileid);

        if (existing) {
            existing.color = val;
            self.seriesStyles.replace(existing, existing);

            const seriesConfig = JSON.parse(
                localStore.getItem(renderer + 'series' + tile.tileid)
            );
            seriesConfig.color = val;
            localStore.setItem(
                renderer + 'series' + tile.tileid,
                JSON.stringify(seriesConfig)
            );
        }
    });

    this.toggleSelected = tile => {
        const selectable =
            self.seriesData().filter(t => t.tileid === tile.tileid).length === 1;

        if (!tile || tile === self.selectedSeriesTile()) {
            self.selectedSeriesTile(null);
        } else if (selectable || tile) {
            self.selectedSeriesTile(tile);
        }
    };

    _.each(
        {
            title: this.chartTitle,
            titlesize: this.titleSize,
            xaxislabel: this.xAxisLabel,
            xaxislabelsize: this.xAxisLabelSize,
            yaxislabel: this.yAxisLabel,
            yaxislabelsize: this.yAxisLabelSize
        },
        (val, key) => {
            val.subscribe(v => localStore.setItem(renderer + key, v));
        }
    );

    this.addAllToChart = tiles => {
        tiles = self.fileViewer ? self.fileViewer.card.tiles() : tiles;
        tiles?.forEach(tile => {
            if (self.stagedSeries().includes(tile.tileid)) {
                self.addData(tile);
            }
        });
    };

    this.addData = tile => {
        const seriesStyle = { tileid: tile.tileid, color: self.colorHolder() };

        const existing = self.seriesStyles().find(el => el.tileid === tile.tileid);
        const stored = localStore.getItem(renderer + 'series' + tile.tileid);

        if (stored) {
            seriesStyle.color = JSON.parse(stored).color;
        } else {
            localStore.setItem(
                renderer + 'series' + tile.tileid,
                JSON.stringify({ color: seriesStyle.color })
            );
        }

        if (!existing) self.seriesStyles.push(seriesStyle);

        const fileInfo = this.fileViewer.getUrl(tile);
        this.getChartingData(tile.tileid, fileInfo.url, fileInfo.name);
        self.toggleSelected(tile);
    };

    this.removeData = tileid => {
        if (self.selectedSeriesTile()?.tileid === tileid) {
            self.selectedSeriesTile(null);
        }

        const existing = self.seriesStyles().find(el => el.tileid === tileid);

        this.seriesData().forEach(series => {
            if (series.tileid === tileid) {
                self.seriesData.remove(series);
                self.stagedSeries.remove(series.tileid);
                localStore.removeItem(renderer + 'series' + series.tileid);
                if (existing) self.seriesStyles.remove(existing);
            }
        });
    };

    this.getChartingData = (tileid, url, name) => {
        if (this.seriesData().some(t => t.tileid === tileid)) return;

        const series = { value: [], count: [] };

        $.ajax({ url, dataType: 'text' }).done(data => {
            self.parse(data, series);
            self.seriesData.push({ tileid, data: series, name });
        });
    };

    this.render = () => {
        const series = { value: [], count: [], name: this.displayContent.name };

        $.ajax({ url: this.displayContent.url, dataType: 'text' }).done(data => {
            try {
                self.parse(data, series);
                self.chartData(undefined);
                self.chartData(series);

                if (self.fileViewer) {
                    self.loadSeriesDataFromLocalStorage();
                } else {
                    self.seriesData.push({ data: series, name: series.name });
                }

                self.displayContent.validRenderer(true);
            } catch {
                self.displayContent.validRenderer(false);
            }

            self.loading(false);
            self.displayContent.validRenderer.valueHasMutated();
        });
    };

    if (this.displayContent && ['render', 'parse'].includes(self.params.context)) {
        this.url = this.displayContent.url;
        this.type = this.displayContent.type;
        self.render();
    }
}
