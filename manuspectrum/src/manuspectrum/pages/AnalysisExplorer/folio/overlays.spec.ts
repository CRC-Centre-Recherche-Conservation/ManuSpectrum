import L from "leaflet";
import { describe, expect, it } from "vitest";

import {
    curtainable,
    folioOverlays,
    layerImageChain,
    layerImageUrl,
    overlayKey,
    overlayPane,
    paneKey,
    removeOverlayPane,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import { boundsOfBox } from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";
import { UNPLACED } from "@/manuspectrum/pages/AnalysisExplorer/folio/registration-store.ts";
import {
    analysisPayload,
    annotation,
    imagingEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { Registration } from "@/manuspectrum/pages/AnalysisExplorer/folio/registration-store.ts";

describe("folio overlays", () => {
    it("asks the IIIF image at a bounded size", () => {
        expect(
            layerImageUrl({
                service: "https://iiif.example/pb/",
                url: null,
                width: 4000,
                height: 3000,
            }),
        ).toBe("https://iiif.example/pb/full/!2048,2048/0/default.jpg");
        expect(
            layerImageUrl({
                service: null,
                url: "https://x/pb.png",
                width: 1,
                height: 1,
            }),
        ).toBe("https://x/pb.png");
        expect(
            layerImageUrl({ service: null, url: null, width: 1, height: 1 }),
        ).toBeNull();
    });

    it("never asks the image server for more than the layer's own size", () => {
        const small = {
            service: "https://iiif.example/pb",
            url: null,
            width: 253,
            height: 271,
        };
        expect(layerImageUrl(small)).toBe(
            "https://iiif.example/pb/full/!253,271/0/default.jpg",
        );
        expect(layerImageUrl(small, 480)).toBe(
            "https://iiif.example/pb/full/!253,271/0/default.jpg",
        );
        expect(layerImageUrl({ ...small, width: 0, height: 0 }, 480)).toBe(
            "https://iiif.example/pb/full/!480,480/0/default.jpg",
        );
    });

    it("falls back to a percentage of the size the server holds, never an upscale, and to max when no size is declared", () => {
        const large = {
            service: "https://iiif.example/pb",
            url: null,
            width: 4000,
            height: 3000,
        };
        expect(layerImageUrl(large, 480, { fallback: true })).toBe(
            "https://iiif.example/pb/full/pct:12/0/default.jpg",
        );
        expect(
            layerImageUrl({ ...large, width: 300, height: 200 }, 480, {
                fallback: true,
            }),
        ).toBe("https://iiif.example/pb/full/pct:100/0/default.jpg");
        expect(
            layerImageUrl({ ...large, width: 0, height: 0 }, 480, {
                fallback: true,
            }),
        ).toBe("https://iiif.example/pb/full/max/0/default.jpg");
        expect(
            layerImageUrl(
                { service: null, url: "https://x/pb.png", width: 1, height: 1 },
                480,
                { fallback: true },
            ),
        ).toBe("https://x/pb.png");
        expect(
            layerImageUrl(
                { service: null, url: null, width: 1, height: 1 },
                480,
                { fallback: true },
            ),
        ).toBeNull();
    });

    it("chains bounded, percentage and max addresses, none twice", () => {
        const large = {
            service: "https://iiif.example/pb",
            url: null,
            width: 4000,
            height: 3000,
        };
        expect(layerImageChain(large, 480)).toEqual([
            "https://iiif.example/pb/full/!480,480/0/default.jpg",
            "https://iiif.example/pb/full/pct:12/0/default.jpg",
            "https://iiif.example/pb/full/max/0/default.jpg",
        ]);
        expect(layerImageChain({ ...large, width: 0, height: 0 }, 480)).toEqual(
            [
                "https://iiif.example/pb/full/!480,480/0/default.jpg",
                "https://iiif.example/pb/full/max/0/default.jpg",
            ],
        );
        expect(
            layerImageChain({
                service: null,
                url: "https://x/pb.png",
                width: 1,
                height: 1,
            }),
        ).toEqual(["https://x/pb.png"]);
        expect(
            layerImageChain({ service: null, url: null, width: 1, height: 1 }),
        ).toEqual([]);
    });

    it("lays the layers switched on in the bounding box of the analysis zone", () => {
        const analysis = analysisPayload({ files: [imagingEntry()] });
        const zone = annotation(1, {
            dataKind: "chemical-imaging",
            shape: { type: "rect", x: 0, y: 0, w: 64, h: 32 },
        });
        const result = folioOverlays(
            analysis,
            {
                [overlayKey(uuid(101), 1)]: {
                    element: "Hg",
                    opacity: 0.6,
                    on: true,
                },
                [overlayKey(uuid(101), 0)]: {
                    element: "Pb",
                    opacity: 0.6,
                    on: false,
                },
            },
            [zone],
        );
        expect(result).toEqual([
            {
                key: `${uuid(101)}:1`,
                url: "https://iiif.example/image/hg/full/!2000,2048/0/default.jpg",
                fallbackUrls: [
                    "https://iiif.example/image/hg/full/pct:68/0/default.jpg",
                    "https://iiif.example/image/hg/full/max/0/default.jpg",
                ],
                bounds: [
                    [-1, 0],
                    [0, 2],
                ],
                opacity: 0.6,
                label: "Hg",
                analysis: uuid(101),
                quarter: 0,
                registered: false,
                canTurn: true,
                zoneBounds: [
                    [-1, 0],
                    [0, 2],
                ],
            },
        ]);
    });

    describe("registered place", () => {
        const on = {
            [overlayKey(uuid(101), 1)]: {
                element: "Hg",
                opacity: 0.6,
                on: true,
            },
        };
        const zone = annotation(1, {
            dataKind: "chemical-imaging",
            shape: { type: "rect", x: 0, y: 0, w: 64, h: 32 },
        });
        const registration = (
            overrides: Partial<Registration> = {},
        ): Registration => ({
            canvas: "canvas-1",
            box: { x: 64, y: 32, w: 128, h: 64 },
            quarter: 1,
            capture: null,
            touched: 1,
            ...overrides,
        });
        const lay = (
            place: { canvas: string | null; registration: Registration | null },
            analysis = analysisPayload({ files: [imagingEntry()] }),
        ) => folioOverlays(analysis, on, [zone], place);

        it("lays the layer in its registered box, turned, on its canvas", () => {
            const [laid] = lay({
                canvas: "canvas-1",
                registration: registration(),
            });
            expect(laid.bounds).toEqual(
                boundsOfBox({ x: 64, y: 32, w: 128, h: 64 }),
            );
            expect(laid.url).toBe(
                "https://iiif.example/image/hg/full/!2048,2000/90/default.jpg",
            );
            expect(laid.quarter).toBe(1);
            expect(laid.registered).toBe(true);
            expect(laid.canTurn).toBe(true);
            expect(laid.zoneBounds).toEqual([
                [-1, 0],
                [0, 2],
            ]);
        });

        it("lays the zone box on another canvas", () => {
            const [laid] = lay({
                canvas: "canvas-2",
                registration: registration(),
            });
            expect(laid.bounds).toEqual(laid.zoneBounds);
            expect(laid.quarter).toBe(0);
            expect(laid.registered).toBe(false);
            expect(laid.url).toContain("/0/default.jpg");
        });

        it("lays the zone box without a registration", () => {
            const [laid] = lay({ canvas: "canvas-1", registration: null });
            expect(laid.registered).toBe(false);
            expect(laid.bounds).toEqual(laid.zoneBounds);
        });

        it("counts an entry that holds only a capture as not registered", () => {
            const [laid] = lay({
                canvas: "canvas-1",
                registration: registration({ box: UNPLACED, quarter: 2 }),
            });
            expect(laid.registered).toBe(false);
            expect(laid.quarter).toBe(0);
            expect(laid.bounds).toEqual(laid.zoneBounds);
        });

        it("drops the quarter of a layer that cannot turn", () => {
            const entry = imagingEntry();
            const flat = {
                ...entry,
                layers: entry.layers.map((layer) => ({
                    ...layer,
                    image: {
                        service: null,
                        url: "https://x/hg.png",
                        width: 10,
                        height: 10,
                    },
                })),
            };
            const [laid] = lay(
                { canvas: "canvas-1", registration: registration() },
                analysisPayload({ files: [flat] }),
            );
            expect(laid.canTurn).toBe(false);
            expect(laid.quarter).toBe(0);
            expect(laid.url).toBe("https://x/hg.png");
            expect(laid.registered).toBe(true);
            expect(laid.bounds).toEqual(
                boundsOfBox({ x: 64, y: 32, w: 128, h: 64 }),
            );
        });

        it("still lists the fallbacks", () => {
            const [laid] = lay({
                canvas: "canvas-1",
                registration: registration(),
            });
            expect(laid.fallbackUrls).toEqual([
                "https://iiif.example/image/hg/full/pct:68/0/default.jpg",
                "https://iiif.example/image/hg/full/max/0/default.jpg",
            ]);
        });
    });

    it("lays nothing when the analysis has only a point on this page", () => {
        const analysis = analysisPayload({ files: [imagingEntry()] });
        const result = folioOverlays(
            analysis,
            {
                [overlayKey(uuid(101), 0)]: {
                    element: "Pb",
                    opacity: 1,
                    on: true,
                },
            },
            [annotation(1)],
        );
        expect(result).toEqual([]);
    });

    it("lets leaflet-side-by-side clip a laid layer through its own pane", () => {
        const map = L.map(document.createElement("div"));
        const name = overlayPane(map, `${uuid(101)}:0`);
        expect(overlayPane(map, `${uuid(101)}:0`)).toBe(name);
        const pane = map.getPane(name)!;
        expect(pane.style.zIndex).toBe("400");
        const overlay = curtainable(
            L.imageOverlay("x.png", [
                [0, 0],
                [1, 1],
            ]),
            pane,
        );
        expect(
            (
                overlay as unknown as { getContainer: () => unknown }
            ).getContainer(),
        ).toBe(pane);
        map.remove();
    });
});

describe("paneKey and removeOverlayPane", () => {
    it("keeps apart two ids that overlayPane would sanitise to the same name", () => {
        const map = L.map(document.createElement("div"));
        const first = overlayPane(map, `stack-${paneKey("https://x/c_1")}`);
        const second = overlayPane(map, `stack-${paneKey("https://x/c-1")}`);
        expect(first).not.toBe(second);
        expect(paneKey("https://x/c_1")).toBe(paneKey("https://x/c_1"));
        map.remove();
    });

    it("takes a pane off the map and lets the name be made again", () => {
        const map = L.map(document.createElement("div"));
        const name = overlayPane(map, "a");
        const pane = map.getPane(name)!;
        removeOverlayPane(map, name);
        expect(map.getPane(name)).toBeUndefined();
        expect(pane.isConnected).toBe(false);
        expect(overlayPane(map, "a")).toBe(name);
        expect(map.getPane(name)).not.toBe(pane);
        removeOverlayPane(map, "never-made");
        map.remove();
    });
});
