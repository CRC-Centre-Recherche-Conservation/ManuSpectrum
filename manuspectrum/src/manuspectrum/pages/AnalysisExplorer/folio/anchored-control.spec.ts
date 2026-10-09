import L from "leaflet";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { anchoredControl } from "@/manuspectrum/pages/AnalysisExplorer/folio/anchored-control.ts";

import { sizedContainer } from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";

type Bounds = [[number, number], [number, number]];

let map: L.Map;
let host: HTMLDivElement;

beforeEach(() => {
    map = L.map(sizedContainer(800, 600), {
        crs: L.CRS.Simple,
        zoomControl: false,
        attributionControl: false,
    });
    map.setView([0, 0], 2, { animate: false });
    host = document.createElement("div");
    map.getContainer().append(host);
});

afterEach(() => {
    map.remove();
    document.body.replaceChildren();
});

function corner(bounds: Bounds): L.Point {
    return map.latLngToContainerPoint([
        Math.max(bounds[0][0], bounds[1][0]),
        Math.max(bounds[0][1], bounds[1][1]),
    ]);
}

describe("anchoredControl", () => {
    it("puts the element at the top-right corner of the bounds", () => {
        const bounds: Bounds = [
            [-20, -30],
            [30, 40],
        ];
        anchoredControl(map, host).place(bounds);
        const point = corner(bounds);
        expect(host.style.position).toBe("absolute");
        expect(host.style.left).toBe(`${point.x}px`);
        expect(host.style.top).toBe(`${point.y}px`);
    });

    it("sits above the top edge, right-aligned, when asked to, kept inside the container", () => {
        const bounds: Bounds = [
            [-20, -30],
            [30, 40],
        ];
        Object.defineProperty(host, "offsetWidth", { value: 120 });
        Object.defineProperty(host, "offsetHeight", { value: 38 });
        const control = anchoredControl(map, host);
        control.place(bounds, 44, true);
        const point = corner(bounds);
        expect(host.style.left).toBe(`${point.x - 120}px`);
        expect(Number.parseFloat(host.style.top)).toBeLessThanOrEqual(
            point.y - 38,
        );
        control.place(
            [
                [4000, 4000],
                [5000, 5000],
            ],
            44,
            true,
        );
        expect(host.style.top).toBe("0px");
    });

    it("sits lower by the stacking offset it is given, kept inside the container", () => {
        const bounds: Bounds = [
            [-20, -30],
            [30, 40],
        ];
        const control = anchoredControl(map, host);
        control.place(bounds, 44);
        expect(host.style.top).toBe(`${corner(bounds).y + 44}px`);
        control.place(
            [
                [-5000, -5000],
                [-4000, -4000],
            ],
            44,
        );
        expect(Number.parseFloat(host.style.top)).toBe(600);
        control.place(bounds);
        expect(host.style.top).toBe(`${corner(bounds).y}px`);
    });

    it("moves with the map on zoom and pan", () => {
        const bounds: Bounds = [
            [-20, -30],
            [30, 40],
        ];
        anchoredControl(map, host).place(bounds);
        map.setView([5, 5], 3, { animate: false });
        const zoomed = corner(bounds);
        expect(host.style.left).toBe(`${zoomed.x}px`);
        expect(host.style.top).toBe(`${zoomed.y}px`);
        map.panBy([10, 20], { animate: false });
        const panned = corner(bounds);
        expect(host.style.left).toBe(`${panned.x}px`);
        expect(host.style.top).toBe(`${panned.y}px`);
    });

    it("keeps the element inside the map container", () => {
        anchoredControl(map, host).place([
            [-5000, -5000],
            [5000, 5000],
        ]);
        expect(host.style.left).toBe("800px");
        expect(host.style.top).toBe("0px");
        anchoredControl(map, host).place([
            [-5000, -5000],
            [-4000, -4000],
        ]);
        expect(Number.parseFloat(host.style.left)).toBe(0);
        expect(Number.parseFloat(host.style.top)).toBe(600);
    });

    it("is placed again when its own size changes", () => {
        let notify: () => void = () => {};
        vi.stubGlobal(
            "ResizeObserver",
            class {
                constructor(callback: () => void) {
                    notify = callback;
                }
                observe() {}
                disconnect() {}
            },
        );
        const bounds: Bounds = [
            [-20, -30],
            [30, 40],
        ];
        anchoredControl(map, host).place(bounds);
        const point = corner(bounds);
        Object.defineProperty(host, "offsetWidth", { value: 120 });
        notify();
        vi.unstubAllGlobals();
        expect(host.style.left).toBe(`${point.x - 120}px`);
    });

    it("stops following the map once removed", () => {
        const control = anchoredControl(map, host);
        control.place([
            [0, 0],
            [10, 10],
        ]);
        control.remove();
        const left = host.style.left;
        map.setView([50, 50], 4, { animate: false });
        expect(host.style.left).toBe(left);
        expect(host.isConnected).toBe(false);
    });
});
