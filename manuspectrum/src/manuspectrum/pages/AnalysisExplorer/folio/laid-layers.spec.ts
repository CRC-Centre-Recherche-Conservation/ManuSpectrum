import L from "leaflet";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { laidLayers } from "@/manuspectrum/pages/AnalysisExplorer/folio/laid-layers.ts";
import { sizedContainer } from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";

import type { FolioOverlay } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";

vi.mock("leaflet-side-by-side", () => ({}));

interface FakeCurtain {
    addTo: ReturnType<typeof vi.fn>;
    on: ReturnType<typeof vi.fn>;
    remove: ReturnType<typeof vi.fn>;
    setRightLayers: ReturnType<typeof vi.fn>;
    _range: HTMLInputElement;
}

let map: L.Map;
let sideBySide: ReturnType<typeof vi.fn>;

function overlay(
    key: string,
    opacity = 1,
    fallbackUrls: string[] = [],
): FolioOverlay {
    return {
        key,
        url: `https://iiif.example/${key}.png`,
        fallbackUrls,
        bounds: [
            [0, 0],
            [-10, 10],
        ],
        opacity,
        label: key,
        analysis: "a",
        quarter: 0,
        registered: false,
        canTurn: true,
        zoneBounds: [
            [0, 0],
            [-10, 10],
        ],
    };
}

function images(): HTMLImageElement[] {
    return [
        ...map
            .getContainer()
            .querySelectorAll<HTMLImageElement>("img.folio-overlay"),
    ];
}

function curtain(index = 0): FakeCurtain {
    return sideBySide.mock.results[index].value as FakeCurtain;
}

beforeEach(() => {
    map = L.map(sizedContainer(), { crs: L.CRS.Simple }).setView([0, 0], 0);
    sideBySide = vi.fn(() => {
        const control: FakeCurtain = {
            addTo: vi.fn(() => control),
            on: vi.fn(() => control),
            remove: vi.fn(),
            setRightLayers: vi.fn(() => control),
            _range: document.createElement("input"),
        };
        return control;
    });
    L.control.sideBySide = sideBySide as unknown as typeof L.control.sideBySide;
});

afterEach(() => {
    map.remove();
});

describe("laidLayers", () => {
    it("lays each layer in a pane of its own, updates it in place and takes it off when it goes", () => {
        const failed = vi.fn();
        const laid = laidLayers(map, { curtainLabel: "Curtain", failed });
        laid.draw([overlay("a:0"), overlay("a:1", 0.5)], null);
        expect(images().map((image) => image.alt)).toEqual(["a:0", "a:1"]);
        expect(map.getPane("folio-overlay-a-1")).toBeDefined();
        const first = images()[0];
        laid.draw([overlay("a:0", 0.25)], null);
        expect(images()).toEqual([first]);
        expect(first.style.opacity).toBe("0.25");
        first.dispatchEvent(new Event("error"));
        expect(failed).toHaveBeenCalledWith("a:0");
        expect(sideBySide).not.toHaveBeenCalled();
    });

    it("tries each fallback address in turn before reporting a failure", () => {
        const failed = vi.fn();
        const laid = laidLayers(map, { curtainLabel: "Curtain", failed });
        laid.draw(
            [
                overlay("a:0", 1, [
                    "https://iiif.example/a:0-pct.png",
                    "https://iiif.example/a:0-max.png",
                ]),
            ],
            null,
        );
        const image = images()[0];
        expect(image.src).toBe("https://iiif.example/a:0.png");
        image.dispatchEvent(new Event("error"));
        expect(image.src).toBe("https://iiif.example/a:0-pct.png");
        image.dispatchEvent(new Event("error"));
        expect(image.src).toBe("https://iiif.example/a:0-max.png");
        expect(failed).not.toHaveBeenCalled();
        image.dispatchEvent(new Event("error"));
        expect(failed).toHaveBeenCalledWith("a:0");
        expect(failed).toHaveBeenCalledTimes(1);
    });

    it("tries each fallback address only once: a redraw does not restart the chain", () => {
        const failed = vi.fn();
        const laid = laidLayers(map, { curtainLabel: "Curtain", failed });
        const chain = ["https://iiif.example/a:0-fallback.png"];
        laid.draw([overlay("a:0", 1, chain)], null);
        const image = images()[0];
        image.dispatchEvent(new Event("error"));
        expect(image.src).toBe("https://iiif.example/a:0-fallback.png");
        laid.draw([overlay("a:0", 0.5, chain)], null);
        image.dispatchEvent(new Event("error"));
        expect(failed).toHaveBeenCalledWith("a:0");
    });

    it("creates one curtain over the layer named, moves it, and takes it off", () => {
        const laid = laidLayers(map, {
            curtainLabel: "Curtain: compare with the page",
            failed: vi.fn(),
        });
        laid.draw([overlay("a:0"), overlay("a:1")], "a:0");
        expect(sideBySide).toHaveBeenCalledTimes(1);
        const [left, right] = sideBySide.mock.calls[0] as [
            L.Layer[],
            L.ImageOverlay,
        ];
        expect(left).toEqual([]);
        expect(right.getElement()?.alt).toBe("a:0");
        expect(curtain().addTo).toHaveBeenCalledWith(map);
        expect(curtain().on).toHaveBeenCalledWith(
            "rightlayerremove",
            expect.any(Function),
        );
        expect(curtain()._range.getAttribute("aria-label")).toBe(
            "Curtain: compare with the page",
        );
        laid.draw([overlay("a:0"), overlay("a:1")], "a:1");
        expect(sideBySide).toHaveBeenCalledTimes(1);
        expect(
            (
                curtain().setRightLayers.mock.calls[0][0] as L.ImageOverlay
            ).getElement()?.alt,
        ).toBe("a:1");
        laid.draw([overlay("a:0")], "a:1");
        expect(curtain().remove).toHaveBeenCalledTimes(1);
        laid.draw([overlay("a:0")], "a:0");
        expect(sideBySide).toHaveBeenCalledTimes(2);
        laid.remove();
        expect(curtain(1).remove).toHaveBeenCalledTimes(1);
    });

    it("clears the clip of a layer leaving the curtain", () => {
        const laid = laidLayers(map, {
            curtainLabel: "Curtain",
            failed: vi.fn(),
        });
        laid.draw([overlay("a:0")], "a:0");
        const unclip = curtain().on.mock.calls[0][1] as (
            event: L.LeafletEvent,
        ) => void;
        const pane = map.getPane("folio-overlay-a-0")!;
        pane.style.clip = "rect(0px, 10px, 10px, 0px)";
        const right = sideBySide.mock.calls[0][1] as L.ImageOverlay;
        unclip({ layer: right } as unknown as L.LeafletEvent);
        expect(pane.style.clip).toBe("");
        unclip({ layer: {} } as unknown as L.LeafletEvent);
    });

    it("forgets layers so the next draw lays them as new images", () => {
        const laid = laidLayers(map, {
            curtainLabel: "Curtain",
            failed: vi.fn(),
        });
        laid.draw([overlay("a:0")], null);
        const before = images()[0];
        laid.forget(["a:0", "unknown"]);
        expect(images()).toEqual([]);
        laid.draw([overlay("a:0")], null);
        expect(images()).toHaveLength(1);
        expect(images()[0]).not.toBe(before);
    });

    it("sets the new address of a layer drawn again, keeping its image and starting its fallbacks over", () => {
        const failed = vi.fn();
        const laid = laidLayers(map, { curtainLabel: "Curtain", failed });
        const chain = ["https://iiif.example/a:0-fallback.png"];
        laid.draw([overlay("a:0", 1, chain)], null);
        const image = images()[0];
        image.dispatchEvent(new Event("error"));
        expect(image.src).toBe("https://iiif.example/a:0-fallback.png");
        const turned = {
            ...overlay("a:0", 0.5, chain),
            url: "https://iiif.example/a:0-turned.png",
            bounds: [
                [0, 0],
                [-4, 4],
            ] as FolioOverlay["bounds"],
        };
        const setUrl = vi.spyOn(L.ImageOverlay.prototype, "setUrl");
        laid.draw([turned], null);
        expect(setUrl).toHaveBeenCalledTimes(1);
        expect(setUrl).toHaveBeenCalledWith(
            "https://iiif.example/a:0-turned.png",
        );
        expect(images()).toEqual([image]);
        expect(image.src).toBe("https://iiif.example/a:0-turned.png");
        expect(image.style.opacity).toBe("0.5");
        laid.draw([turned], null);
        expect(setUrl).toHaveBeenCalledTimes(1);
        image.dispatchEvent(new Event("error"));
        expect(image.src).toBe("https://iiif.example/a:0-fallback.png");
        expect(failed).not.toHaveBeenCalled();
        setUrl.mockRestore();
    });
});
