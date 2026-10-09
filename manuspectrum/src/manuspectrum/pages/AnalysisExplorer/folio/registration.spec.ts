import { describe, expect, it } from "vitest";

import {
    boundsOfBox,
    boxOfBounds,
    captureRegion,
    captureUrl,
    moveBox,
    resizeFromCorner,
    rotatedImageUrl,
    scaleBox,
    turn,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";

const box = { x: 100, y: 200, w: 300, h: 100 };

describe("registration math", () => {
    it("goes from a box to Leaflet bounds and back", () => {
        expect(boxOfBounds(boundsOfBox(box))).toEqual(box);
        const origin = { x: 0, y: 0, w: 10, h: 10 };
        expect(boxOfBounds(boundsOfBox(origin))).toEqual(origin);
    });

    it("turns around the centre and swaps the sides", () => {
        const once = turn(box, 0, 1);
        expect(once.quarter).toBe(1);
        expect(once.box).toEqual({ x: 200, y: 100, w: 100, h: 300 });
        expect(turn(once.box, 1, -1)).toEqual({ box, quarter: 0 });
        expect(turn(box, 0, -1).quarter).toBe(3);
    });

    it("moves and scales", () => {
        expect(moveBox(box, 10, -5)).toEqual({
            x: 110,
            y: 195,
            w: 300,
            h: 100,
        });
        expect(scaleBox(box, 2, "centre")).toEqual({
            x: -50,
            y: 150,
            w: 600,
            h: 200,
        });
        expect(scaleBox(box, 0.5, "nw")).toEqual({
            x: 100,
            y: 200,
            w: 150,
            h: 50,
        });
    });

    it("resizes from a corner, keeping the ratio unless told otherwise", () => {
        expect(resizeFromCorner(box, "se", { x: 700, y: 400 }, true)).toEqual({
            x: 100,
            y: 200,
            w: 600,
            h: 200,
        });
        expect(resizeFromCorner(box, "se", { x: 700, y: 400 }, false)).toEqual({
            x: 100,
            y: 200,
            w: 600,
            h: 200,
        });
        expect(resizeFromCorner(box, "nw", { x: 0, y: 0 }, false)).toEqual({
            x: 0,
            y: 0,
            w: 400,
            h: 300,
        });
        expect(
            resizeFromCorner(box, "se", { x: 101, y: 201 }, true).w,
        ).toBeGreaterThanOrEqual(8);
    });

    it("asks the image service for the turned layer", () => {
        const image = {
            service: "https://img.example/iiif/a",
            url: null,
            width: 4000,
            height: 2000,
        };
        expect(rotatedImageUrl(image, 1)).toBe(
            "https://img.example/iiif/a/full/!2000,2048/90/default.jpg",
        );
        expect(rotatedImageUrl(image, 0)).toBe(
            "https://img.example/iiif/a/full/!2048,2000/0/default.jpg",
        );
        expect(
            rotatedImageUrl(
                { ...image, service: null, url: "https://x.example/a.png" },
                1,
            ),
        ).toBeNull();
    });

    it("maps the box onto the served page pixels, clamped to the page", () => {
        const page = {
            bounds: boundsOfBox({ x: 0, y: 0, w: 1000, h: 500 }),
            served: { w: 4000, h: 2000 },
        };
        expect(captureRegion(box, page)).toEqual({
            x: 400,
            y: 800,
            w: 1200,
            h: 400,
        });
        expect(captureRegion({ x: 900, y: 450, w: 300, h: 100 }, page)).toEqual(
            { x: 3600, y: 1800, w: 400, h: 200 },
        );
        expect(
            captureRegion({ x: 2000, y: 2000, w: 10, h: 10 }, page),
        ).toBeNull();
    });

    it("writes the capture URL with the size and the turn undone", () => {
        expect(
            captureUrl(
                "https://img.example/iiif/p",
                { x: 400, y: 800, w: 1200, h: 400 },
                { w: 600, h: 200 },
                1,
            ),
        ).toBe(
            "https://img.example/iiif/p/400,800,1200,400/600,200/270/default.jpg",
        );
    });
});
