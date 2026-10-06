import L from "leaflet";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { sizedContainer } from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";
import {
    applyView,
    fitView,
    fitZoomOf,
    keepsFit,
    readView,
    watchPane,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-sync.ts";

import type { SyncTarget } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-sync.ts";

const LARGE = { w: 2000, h: 3000 };
const SMALL = { w: 1000, h: 1500 };

const maps: L.Map[] = [];

function pane(size = LARGE, width = 800, height = 600): SyncTarget {
    const map = L.map(sizedContainer(width, height), {
        crs: L.CRS.Simple,
        zoomSnap: 0.25,
        minZoom: -10,
        attributionControl: false,
    });
    maps.push(map);
    const target: SyncTarget = { map, size, nativeZoom: 0 };
    map.setView([0, 0], 0, { animate: false });
    return target;
}

function centreOf(target: SyncTarget): { cx: number; cy: number } {
    const point = target.map.project(target.map.getCenter(), 0);
    return { cx: point.x / target.size.w, cy: point.y / target.size.h };
}

afterEach(() => {
    maps.splice(0).forEach((map) => map.remove());
    vi.unstubAllGlobals();
});

describe("readView and fitZoomOf", () => {
    it("reads the fitted image as its centre at one half and no relative zoom", () => {
        const target = pane();
        const fit = fitZoomOf(target) as number;
        target.map.setView(target.map.unproject([1000, 1500], 0), fit, {
            animate: false,
        });
        const view = readView(target, "c1");
        expect(view?.cx).toBeCloseTo(0.5, 3);
        expect(view?.cy).toBeCloseTo(0.5, 3);
        expect(view?.dz).toBeCloseTo(0, 5);
        expect(view?.size).toEqual(LARGE);
        expect(view?.origin).toBe("c1");
    });

    it("measures the zoom against the fit of this image, not of the map", () => {
        const large = pane(LARGE);
        const small = pane(SMALL);
        expect(fitZoomOf(small)).toBeGreaterThan(fitZoomOf(large) as number);
        small.map.setZoom((fitZoomOf(small) as number) + 3, {
            animate: false,
        });
        expect(readView(small, "s")?.dz).toBeCloseTo(3, 5);
    });

    it("reads nothing while the map has no size", () => {
        const hidden = pane(LARGE, 0, 0);
        expect(fitZoomOf(hidden)).toBeNull();
        expect(readView(hidden, "h")).toBeNull();
    });
});

describe("fitView", () => {
    it("shows the whole image centred and lets the reader zoom out two levels below it", () => {
        const target = pane();
        const zoom = fitZoomOf(target) as number;
        fitView(target, zoom);
        expect(target.map.getZoom()).toBe(zoom);
        expect(target.map.getMinZoom()).toBe(zoom - 2);
        expect(keepsFit(target)).toBe(true);
    });

    it("never asks Leaflet to zoom to the new minimum, which would end an animated zoom over the fit", () => {
        const target = pane(LARGE, 800, 600);
        target.map.setMinZoom(-8);
        target.map.setView([0, 0], -7, { animate: false });
        const setZoom = vi.spyOn(target.map, "setZoom");
        const zoom = fitZoomOf(target) as number;
        fitView(target, zoom);
        expect(setZoom).not.toHaveBeenCalled();
        expect(target.map.getZoom()).toBe(zoom);
    });

    it("fits an image whose fit lies below the zoom range the map had", () => {
        const target = pane(LARGE, 800, 600);
        const zoom = fitZoomOf(target) as number;
        target.map.setMinZoom(3);
        target.map.setZoom(4, { animate: false });
        expect(zoom).toBeLessThan(3);
        fitView(target, zoom);
        expect(target.map.getZoom()).toBe(zoom);
    });
});

describe("keepsFit", () => {
    function fitted(target: SyncTarget): void {
        target.map.setView(
            target.map.unproject(
                [target.size.w / 2, target.size.h / 2],
                target.nativeZoom,
            ),
            fitZoomOf(target) as number,
            { animate: false },
        );
    }

    it("is true while the view is the fit of the whole image", () => {
        const target = pane();
        fitted(target);
        expect(keepsFit(target)).toBe(true);
    });

    it("is false once the reader zoomed or moved", () => {
        const zoomed = pane();
        fitted(zoomed);
        zoomed.map.setZoom(zoomed.map.getZoom() + 1, { animate: false });
        expect(keepsFit(zoomed)).toBe(false);
        const moved = pane();
        fitted(moved);
        moved.map.panBy([120, 0], { animate: false });
        expect(keepsFit(moved)).toBe(false);
    });

    it("tolerates the pixel Leaflet rounds a pan to when its container is resized", () => {
        const target = pane();
        fitted(target);
        target.map.panBy([1, 0], { animate: false });
        expect(keepsFit(target)).toBe(true);
        target.map.panBy([5, 0], { animate: false });
        expect(keepsFit(target)).toBe(false);
    });

    it("is true while the map has no size, nothing being fitted yet", () => {
        expect(keepsFit(pane(LARGE, 0, 0))).toBe(true);
    });
});

describe("applyView", () => {
    it("carries the centre and the zoom between panes served at the same size", () => {
        const source = pane(LARGE);
        const target = pane(LARGE);
        source.map.setView(
            source.map.unproject([400, 2500], 0),
            (fitZoomOf(source) as number) + 2,
            { animate: false },
        );
        const view = readView(source, "a");
        expect(applyView(target, view!)).toBe("full");
        expect(centreOf(target).cx).toBeCloseTo(0.2, 3);
        expect(centreOf(target).cy).toBeCloseTo(2500 / 3000, 3);
        expect(target.map.getZoom()).toBeCloseTo(source.map.getZoom(), 5);
    });

    it("carries only the relative zoom between panes served at different sizes and leaves the centre alone", () => {
        const source = pane(LARGE);
        const target = pane(SMALL);
        const before = target.map.getCenter();
        source.map.setView(
            source.map.unproject([400, 2500], 0),
            (fitZoomOf(source) as number) + 2,
            { animate: false },
        );
        expect(applyView(target, readView(source, "a")!)).toBe("zoom");
        expect(target.map.getCenter().lat).toBeCloseTo(before.lat, 6);
        expect(target.map.getCenter().lng).toBeCloseTo(before.lng, 6);
        expect(
            target.map.getZoom() - (fitZoomOf(target) as number),
        ).toBeCloseTo(2, 5);
    });

    it("does nothing while its own map has no size", () => {
        const source = pane(LARGE);
        const hidden = pane(LARGE, 0, 0);
        expect(applyView(hidden, readView(source, "a")!)).toBeNull();
    });
});

describe("watchPane", () => {
    let frames: FrameRequestCallback[];

    beforeEach(() => {
        frames = [];
        vi.stubGlobal(
            "requestAnimationFrame",
            (callback: FrameRequestCallback) => frames.push(callback),
        );
        vi.stubGlobal("cancelAnimationFrame", () => {
            frames = [];
        });
    });

    function run(): void {
        const pending = frames;
        frames = [];
        pending.forEach((callback) => callback(0));
    }

    it("emits one view per animation frame, however many moves came", () => {
        const target = pane();
        const emit = vi.fn();
        const watcher = watchPane({
            target: () => target,
            origin: () => "a",
            emit,
        });
        target.map.setZoom(-1, { animate: false });
        target.map.panBy([40, 10], { animate: false });
        target.map.setZoom(0, { animate: false });
        expect(emit).not.toHaveBeenCalled();
        run();
        expect(emit).toHaveBeenCalledTimes(1);
        watcher.destroy();
    });

    it("does not bounce: a view applied from outside is not emitted again", () => {
        const source = pane();
        const target = pane();
        const emit = vi.fn();
        const watcher = watchPane({
            target: () => target,
            origin: () => "b",
            emit,
        });
        source.map.setView(
            source.map.unproject([300, 300], 0),
            (fitZoomOf(source) as number) + 1,
            { animate: false },
        );
        watcher.apply(readView(source, "a")!);
        run();
        expect(emit).not.toHaveBeenCalled();
        expect(target.map.getZoom()).toBeCloseTo(source.map.getZoom(), 5);
        watcher.destroy();
    });

    it("ignores a view that comes from its own canvas", () => {
        const target = pane();
        const watcher = watchPane({
            target: () => target,
            origin: () => "a",
            emit: vi.fn(),
        });
        const spy = vi.spyOn(target.map, "setView");
        watcher.apply({ cx: 0.1, cy: 0.1, dz: 2, size: LARGE, origin: "a" });
        expect(spy).not.toHaveBeenCalled();
        watcher.destroy();
    });

    it("moves silently: a fit of its own is not a reader's move", () => {
        const target = pane();
        const emit = vi.fn();
        const watcher = watchPane({
            target: () => target,
            origin: () => "a",
            emit,
        });
        watcher.silently(() => target.map.setZoom(-2, { animate: false }));
        run();
        expect(emit).not.toHaveBeenCalled();
        watcher.destroy();
    });

    it("stops listening once destroyed", () => {
        const target = pane();
        const emit = vi.fn();
        watchPane({ target: () => target, origin: () => "a", emit }).destroy();
        target.map.setZoom(-1, { animate: false });
        run();
        expect(emit).not.toHaveBeenCalled();
    });
});
