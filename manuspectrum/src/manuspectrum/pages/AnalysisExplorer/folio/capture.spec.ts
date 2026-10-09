import { afterEach, describe, expect, it, vi } from "vitest";

import {
    layerSizeOf,
    planCapture,
    probeImage,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/capture.ts";

const SERVICE = "https://iiif.example/folio";
// A 2000 x 3000 page served at its own size: bounds = size / 2^6 units.
const PAGE = {
    bounds: [
        [-3000 / 64, 0],
        [0, 2000 / 64],
    ] as [[number, number], [number, number]],
    served: { w: 2000, h: 3000 },
};

describe("planCapture", () => {
    const box = { x: 320, y: 640, w: 640, h: 960 };

    it("builds the region url at the layer size with the turn undone", () => {
        const plan = planCapture({
            page: PAGE,
            service: SERVICE,
            box,
            quarter: 1,
            layerSize: { w: 900, h: 600 },
        });
        expect(plan).toEqual({
            url: `${SERVICE}/640,1280,1280,1720/600,900/270/default.jpg`,
            width: 900,
            height: 600,
        });
    });

    it("answers null without a page, without a service or off the page", () => {
        const base = { box, quarter: 0 as const, layerSize: { w: 10, h: 10 } };
        expect(
            planCapture({ ...base, page: null, service: SERVICE }),
        ).toBeNull();
        expect(planCapture({ ...base, page: PAGE, service: null })).toBeNull();
        expect(
            planCapture({
                ...base,
                page: PAGE,
                service: SERVICE,
                box: { x: 90000, y: 90000, w: 10, h: 10 },
            }),
        ).toBeNull();
    });
});

describe("probeImage", () => {
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    function stubImage(outcome: "load" | "error" | "never") {
        class Fake {
            onload: (() => void) | null = null;
            onerror: (() => void) | null = null;
            set src(_: string) {
                if (outcome === "load") queueMicrotask(() => this.onload?.());
                if (outcome === "error") queueMicrotask(() => this.onerror?.());
            }
        }
        vi.stubGlobal("Image", Fake);
    }

    it("resolves true when the image loads", async () => {
        stubImage("load");
        expect(await probeImage("https://x/y.jpg")).toBe(true);
    });

    it("resolves false on error", async () => {
        stubImage("error");
        expect(await probeImage("https://x/y.jpg")).toBe(false);
    });

    it("resolves false after 15 seconds of silence", async () => {
        vi.useFakeTimers();
        stubImage("never");
        const result = probeImage("https://x/y.jpg");
        await vi.advanceTimersByTimeAsync(15000);
        expect(await result).toBe(false);
    });
});

describe("layerSizeOf", () => {
    afterEach(() => vi.unstubAllGlobals());

    it("reads the info.json of the layer's service", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => ({
                ok: true,
                json: async () => ({ width: 800, height: 600 }),
            })),
        );
        expect(await layerSizeOf("https://iiif.example/layer", null)).toEqual({
            w: 800,
            h: 600,
        });
    });

    it("falls back to the laid image's natural size", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => {
                throw new Error("down");
            }),
        );
        const element = { naturalWidth: 300, naturalHeight: 200 };
        expect(
            await layerSizeOf(
                "https://iiif.example/layer",
                element as HTMLImageElement,
            ),
        ).toEqual({ w: 300, h: 200 });
    });

    it("swaps the sides of a laid image turned an odd quarter", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => ({ ok: false })),
        );
        const element = { naturalWidth: 300, naturalHeight: 200 };
        expect(
            await layerSizeOf(
                "https://iiif.example/layer",
                element as HTMLImageElement,
                1,
            ),
        ).toEqual({ w: 200, h: 300 });
    });

    it("answers null when nothing tells the size", async () => {
        expect(await layerSizeOf(null, null)).toBeNull();
    });
});
