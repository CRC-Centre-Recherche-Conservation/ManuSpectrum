// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science

import $ from 'jquery';
import ko from 'knockout';
import Plotly from 'plotly.js-dist';

const plotlyBinding = {
    init(element, valueAccessor) {
        const config = ko.unwrap(valueAccessor());
        const useTracesMode = typeof config.traces === 'function';

        let traces;
        if (useTracesMode) {
            traces = ko.unwrap(config.traces) || [];
        } else {
            const data = config.data();

            const multiSeriesColors = [
                config.primarySeriesColor || '#3333ff',
                '#ff6633', '#33cc33', '#cc33ff', '#ffcc00',
                '#00cccc', '#ff3366', '#6633ff'
            ];

            if (data.series && Array.isArray(data.series)) {
                traces = data.series.map((s, i) => {
                    const trace = {
                        x: s.value,
                        y: s.count,
                        type: 'scatter',
                        mode: 'lines',
                        name: s.name,
                        line: {
                            color: multiSeriesColors[i % multiSeriesColors.length],
                            width: i === 0 ? 3 : 2
                        }
                    };
                    if (s.yaxis) {
                        trace.yaxis = s.yaxis;
                    }
                    return trace;
                });
            } else {
                traces = [{
                    x: data.value,
                    y: data.count,
                    type: 'scatter',
                    mode: 'lines',
                    name: data.name,
                    line: {
                        color: config.primarySeriesColor,
                        width: 3
                    }
                }];
            }
        }

        const layout = {
            title: {
                text: config.title(),
                font: {
                    family: 'Arial, monospace',
                    size: config.titleSize()
                },
                xref: 'paper',
                x: 0.05
            },
            xaxis: {
                title: {
                    text: config.xAxisLabel(),
                    font: {
                        family: 'Arial, monospace',
                        size: config.xAxisLabelSize(),
                        color: '#7f7f7f'
                    }
                }
            },
            yaxis: {
                title: {
                    text: config.yAxisLabel(),
                    font: {
                        family: 'Arial, monospace',
                        size: config.yAxisLabelSize(),
                        color: '#7f7f7f'
                    }
                }
            },
            legend: {
                font: {
                    family: 'Arial, monospace',
                    color: '#7f7f7f'
                }
            },
            width: $(element).width() - 2,
        };

        // Dual Y axis support
        const yRightLabel = config.yAxisRightLabel
            ? ko.unwrap(config.yAxisRightLabel)
            : '';
        if (yRightLabel) {
            layout.yaxis2 = {
                title: {
                    text: yRightLabel,
                    font: {
                        family: 'Arial, monospace',
                        size: config.yAxisLabelSize
                            ? ko.unwrap(config.yAxisLabelSize)
                            : 17,
                        color: '#7f7f7f',
                    },
                },
                overlaying: 'y',
                side: 'right',
            };
        }

        const chartConfig = {
            responsive: false,
            modeBarButtonsToAdd: [{
                name: 'expand height',
                icon: {
                    width: 1800,
                    height: 1400,
                    path: "M704 1216q0 -26 -19 -45t-45 -19h-128v-1024h128q26 0 45 -19t19 -45t-19 -45l-256 -256q-19 -19 -45 -19t-45 19l-256 256q-19 19 -19 45t19 45t45 19h128v1024h-128q-26 0 -45 19t-19 45t19 45l256 256q19 19 45 19t45 -19l256 -256q19 -19 19 -45z"
                },
                click() {
                    config.autosize =
                        ko.unwrap(config.autosize) === undefined
                            ? false
                            : !ko.unwrap(config.autosize);

                    layout.height = !ko.unwrap(config.autosize)
                        ? ko.unwrap(config.height) || window.innerHeight - 250
                        : 450;

                    Plotly.relayout(element, layout);
                }
            }, {
                name: 'fullscreen',
                icon: {
                    width: 1000,
                    height: 1000,
                    path: "M200 800V600H0v350q0 21 14.5 35.5T50 1000h350V800H200zM0 400h200V200h200V0H50Q29 0 14.5 14.5T0 50v350zm800 400H600v200h350q21 0 35.5-14.5T1000 950V600H800v200zM600 0v200h200v200h200V50q0-21-14.5-35.5T950 0H600z"
                },
                click() {
                    if (!document.fullscreenElement) {
                        element._savedWidth = $(element).parent().width() - 2;
                        element._savedHeight = layout.height;
                        element.requestFullscreen().then(() => {
                            element.style.background = '#fff';
                            layout.width = window.innerWidth - 20;
                            layout.height = window.innerHeight - 20;
                            Plotly.relayout(element, layout);
                        });
                    } else {
                        document.exitFullscreen();
                    }
                }
            }]
        };

        document.addEventListener('fullscreenchange', () => {
            if (!document.fullscreenElement && element.isConnected) {
                element.style.background = '';
                layout.width = element._savedWidth || $(element).parent().width() - 2;
                layout.height = element._savedHeight || 450;
                Plotly.relayout(element, layout);
            }
        });

        Plotly.newPlot(element, traces, layout, chartConfig);

        $(window).on('resize.plotlyBinding', () => {
            layout.width = $(element).width() - 2;
            Plotly.relayout(element, layout);
        });

        config.title.subscribe(val => {
            layout.title.text = val;
            Plotly.relayout(element, layout);
        });

        config.titleSize.subscribe(val => {
            layout.title.font.size = val;
            Plotly.relayout(element, layout);
        });

        config.xAxisLabel.subscribe(val => {
            layout.xaxis.title.text = val;
            Plotly.relayout(element, layout);
        });

        config.xAxisLabelSize.subscribe(val => {
            layout.xaxis.title.font.size = val;
            Plotly.relayout(element, layout);
        });

        config.yAxisLabel.subscribe(val => {
            layout.yaxis.title.text = val;
            Plotly.relayout(element, layout);
        });

        config.yAxisLabelSize.subscribe(val => {
            layout.yaxis.title.font.size = val;
            Plotly.relayout(element, layout);
        });

        if (config.yAxisRightLabel && ko.isObservable(config.yAxisRightLabel)) {
            config.yAxisRightLabel.subscribe((val) => {
                if (val) {
                    if (!layout.yaxis2) {
                        layout.yaxis2 = {
                            overlaying: 'y',
                            side: 'right',
                            title: {
                                font: {
                                    family: 'Arial, monospace',
                                    size: 17,
                                    color: '#7f7f7f',
                                },
                            },
                        };
                    }
                    layout.yaxis2.title.text = val;
                } else {
                    delete layout.yaxis2;
                }
                Plotly.relayout(element, layout);
            });
        }

        if (useTracesMode) {
            config.traces.subscribe(newTraces => {
                Plotly.react(element, newTraces || [], layout, chartConfig);
            });
        } else {
            config.seriesStyles.subscribe(val => {
                if (val.length >= 1) {
                    val.forEach(style => {
                        let traceIndices = [];
                        element.data.forEach((trace, i) => {
                            if (trace.tileid === style.tileid) {
                                traceIndices = [i];
                            }
                        });
                        if (traceIndices.length === 1) {
                            Plotly.restyle(
                                element,
                                { 'marker.color': style.color },
                                traceIndices
                            );
                        }
                    });
                }
            });

            config.seriesData.subscribe(val => {
                val.forEach(series => {
                    if (series.status === 'added') {
                        const style = config.seriesStyles().find(
                            el => el.tileid === series.value.tileid
                        );
                        if (style) {
                            Plotly.addTraces(
                                element,
                                {
                                    x: series.value.data.value,
                                    y: series.value.data.count,
                                    opacity: 0.9,
                                    marker: { color: style.color },
                                    name: series.value.name,
                                    tileid: series.value.tileid
                                },
                                element.data.length
                            );
                        }
                    } else {
                        element.data.forEach((trace, i) => {
                            if (trace.name === series.value.name) {
                                Plotly.deleteTraces(element, i);
                            }
                        });
                    }
                });
            }, this, 'arrayChange');
        }

        ko.utils.domNodeDisposal.addDisposeCallback(element, () => {
            $(window).off('resize.plotlyBinding');
        });
    }
};

ko.bindingHandlers.plotly = plotlyBinding;

export default plotlyBinding;
