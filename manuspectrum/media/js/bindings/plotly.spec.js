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

const attach = () => {
    const element = document.createElement('div');
    document.body.appendChild(element);
    return element;
};

const mount = async (config) => {
    const element = attach();
    await plotlyBinding.init(element, () => config);
    return element;
};

describe('plotly binding loading', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    afterEach(() => {
        $(window).off('resize');
        document.body.innerHTML = '';
    });

    it('draws once Plotly has loaded', async () => {
        const element = await mount(buildConfig());

        expect(plotly.newPlot).toHaveBeenCalledWith(
            element,
            expect.any(Array),
            expect.any(Object),
            expect.any(Object)
        );
    });

    it('never draws into a node disposed while Plotly loads', async () => {
        const config = buildConfig();
        const element = attach();
        const pending = plotlyBinding.init(element, () => config);

        ko.cleanNode(element);
        await pending;

        expect(plotly.newPlot).not.toHaveBeenCalled();
        expect(plotly.purge).not.toHaveBeenCalled();
        OBSERVED.forEach((key) => {
            expect(config[key].getSubscriptionsCount()).toBe(0);
        });
    });
});

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

    it('disposes every chart-formatting subscription it took', async () => {
        const config = buildConfig();
        const element = await mount(config);

        OBSERVED.forEach((key) => {
            expect(config[key].getSubscriptionsCount()).toBeGreaterThan(0);
        });

        ko.cleanNode(element);

        OBSERVED.forEach((key) => {
            expect(config[key].getSubscriptionsCount()).toBe(0);
        });
    });

    it('removes its fullscreenchange listener from document', async () => {
        const element = await mount(buildConfig());

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

    it('purges the Plotly graph so the detached node releases its traces', async () => {
        const element = await mount(buildConfig());

        ko.cleanNode(element);

        expect(plotly.purge).toHaveBeenCalledWith(element);
    });

    it('keeps a second chart resizing after the first is disposed', async () => {
        const first = await mount(buildConfig());
        const second = await mount(buildConfig());

        ko.cleanNode(first);
        plotly.relayout.mockClear();
        $(window).trigger('resize');

        expect(plotly.relayout).toHaveBeenCalledTimes(1);
        expect(plotly.relayout).toHaveBeenCalledWith(
            second,
            expect.any(Object)
        );
    });

    it('disposes the traces subscription of the report chart too', async () => {
        const config = buildTracesConfig();
        const element = await mount(config);
        expect(config.traces.getSubscriptionsCount()).toBeGreaterThan(0);

        ko.cleanNode(element);
        plotly.react.mockClear();
        config.traces([{ x: [1], y: [2] }]);

        expect(config.traces.getSubscriptionsCount()).toBe(0);
        expect(plotly.react).not.toHaveBeenCalled();
    });

    it('stops relaying observable changes to a disposed chart', async () => {
        const config = buildConfig();
        const element = await mount(config);

        ko.cleanNode(element);
        plotly.relayout.mockClear();
        config.title('Renamed');

        expect(plotly.relayout).not.toHaveBeenCalled();
    });
});

describe('plotly binding logarithmic Y', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    afterEach(() => {
        $(window).off('resize');
        document.body.innerHTML = '';
    });

    const logConfig = (yLog) => ({
        ...buildTracesConfig(),
        traces: ko.observable([{ x: [1, 2, 3], y: [0, 5, 10] }]),
        yLog: ko.observable(yLog),
    });

    it('draws linear when the toggle is off', async () => {
        await mount(logConfig(false));

        const [, traces, layout] = plotly.newPlot.mock.calls[0];
        expect(layout.yaxis.type).toBe('linear');
        expect(traces[0].y).toEqual([0, 5, 10]);
    });

    it('draws a log axis with the zeros clamped when the toggle is on', async () => {
        await mount(logConfig(true));

        const [, traces, layout] = plotly.newPlot.mock.calls[0];
        expect(layout.yaxis.type).toBe('log');
        expect(traces[0].y).toEqual([5, 5, 10]);
        expect(traces[0].customdata).toEqual([0, 5, 10]);
    });

    it('redraws when the toggle changes, from the unmodified data', async () => {
        const config = logConfig(false);
        await mount(config);

        config.yLog(true);
        const [, logTraces, logLayout] = plotly.react.mock.calls.at(-1);
        expect(logLayout.yaxis.type).toBe('log');
        expect(logTraces[0].y).toEqual([5, 5, 10]);

        config.yLog(false);
        const [, linTraces, linLayout] = plotly.react.mock.calls.at(-1);
        expect(linLayout.yaxis.type).toBe('linear');
        expect(linTraces[0].y).toEqual([0, 5, 10]);
        expect(config.traces()[0].y).toEqual([0, 5, 10]);
    });

    it('stays linear when a curve has nothing positive', async () => {
        const config = logConfig(true);
        config.traces([{ x: [1, 2], y: [0, 0] }]);
        await mount(config);

        expect(plotly.newPlot.mock.calls[0][2].yaxis.type).toBe('linear');
    });

    it('disposes the toggle subscription', async () => {
        const config = logConfig(false);
        const element = await mount(config);
        ko.cleanNode(element);

        expect(config.yLog.getSubscriptionsCount()).toBe(0);
    });
});
