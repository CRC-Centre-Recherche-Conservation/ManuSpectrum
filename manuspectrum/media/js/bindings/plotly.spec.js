/**
 * Vitest unit spec — bindings/plotly.js teardown.
 *
 * The binding sits inside a `ko if:` (file-xy.htm, afs-reader.htm), so ticking
 * a file in the workbench dropdown destroys and rebuilds the chart. Its
 * observables live on `params.state` and on the module-level node registry, so
 * anything the binding subscribes to outlives the node it drew into.
 *
 * Note: this file lives under media/js/bindings/, which coverage.include does
 * not target, so it executes without touching the coverage gate.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import $ from 'jquery';
import ko from 'knockout';

import plotlyBinding from './plotly.js';

const plotly = vi.hoisted(() => ({
    newPlot: vi.fn(),
    react: vi.fn(),
    relayout: vi.fn(),
    restyle: vi.fn(),
    addTraces: vi.fn(),
    deleteTraces: vi.fn(),
    purge: vi.fn(),
}));

vi.mock('plotly.js-cartesian-dist', () => ({ default: plotly }));

const buildConfig = () => ({
    data: () => ({ value: [1, 2, 3], count: [4, 5, 6], name: 'spectrum' }),
    primarySeriesColor: '#3333ff',
    title: ko.observable('Data'),
    titleSize: ko.observable(24),
    xAxisLabel: ko.observable('X'),
    xAxisLabelSize: ko.observable(17),
    yAxisLabel: ko.observable('Y'),
    yAxisLabelSize: ko.observable(17),
    yAxisRightLabel: ko.observable(''),
    seriesStyles: ko.observableArray([]),
    seriesData: ko.observableArray([]),
});

const OBSERVED = [
    'title',
    'titleSize',
    'xAxisLabel',
    'xAxisLabelSize',
    'yAxisLabel',
    'yAxisLabelSize',
    'yAxisRightLabel',
    'seriesStyles',
    'seriesData',
];

// The other shape the binding takes: file-xy.htm binds the report chart to a
// single `traces` computed instead of the seriesStyles/seriesData pair.
const buildTracesConfig = () => ({
    ...buildConfig(),
    traces: ko.observable([]),
});

const mount = (config) => {
    const element = document.createElement('div');
    document.body.appendChild(element);
    plotlyBinding.init(element, () => config);
    return element;
};

describe('plotly binding disposal', () => {
    let addListener;
    let removeListener;

    beforeEach(() => {
        vi.clearAllMocks();
        addListener = vi.spyOn(document, 'addEventListener');
        removeListener = vi.spyOn(document, 'removeEventListener');
    });

    afterEach(() => {
        vi.restoreAllMocks();
        $(window).off('resize');
        document.body.innerHTML = '';
    });

    it('disposes every chart-formatting subscription it took', () => {
        const config = buildConfig();
        const element = mount(config);

        OBSERVED.forEach((key) => {
            expect(config[key].getSubscriptionsCount()).toBeGreaterThan(0);
        });

        ko.cleanNode(element);

        OBSERVED.forEach((key) => {
            expect(config[key].getSubscriptionsCount()).toBe(0);
        });
    });

    it('removes its fullscreenchange listener from document', () => {
        const element = mount(buildConfig());

        const registered = addListener.mock.calls.find(
            ([type]) => type === 'fullscreenchange'
        );
        expect(registered).toBeDefined();

        ko.cleanNode(element);

        expect(removeListener).toHaveBeenCalledWith(
            'fullscreenchange',
            registered[1]
        );
    });

    it('purges the Plotly graph so the detached node releases its traces', () => {
        const element = mount(buildConfig());

        ko.cleanNode(element);

        expect(plotly.purge).toHaveBeenCalledWith(element);
    });

    it('keeps a second chart resizing after the first is disposed', () => {
        const first = mount(buildConfig());
        const second = mount(buildConfig());

        ko.cleanNode(first);
        plotly.relayout.mockClear();
        $(window).trigger('resize');

        expect(plotly.relayout).toHaveBeenCalledTimes(1);
        expect(plotly.relayout).toHaveBeenCalledWith(
            second,
            expect.any(Object)
        );
    });

    it('disposes the traces subscription of the report chart too', () => {
        const config = buildTracesConfig();
        const element = mount(config);
        expect(config.traces.getSubscriptionsCount()).toBeGreaterThan(0);

        ko.cleanNode(element);
        plotly.react.mockClear();
        config.traces([{ x: [1], y: [2] }]);

        expect(config.traces.getSubscriptionsCount()).toBe(0);
        expect(plotly.react).not.toHaveBeenCalled();
    });

    it('stops relaying observable changes to a disposed chart', () => {
        const config = buildConfig();
        const element = mount(config);

        ko.cleanNode(element);
        plotly.relayout.mockClear();
        config.title('Renamed');

        expect(plotly.relayout).not.toHaveBeenCalled();
    });
});
