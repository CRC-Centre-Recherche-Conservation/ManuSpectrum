import { describe, expect, it } from "vitest";

import {
    boundsOfBox,
    boxOfBounds,
    captureRegion,
    captureUrl,
    moveBox,
    resizeFromCorner,
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

    it("maps the box onto the served page pixels", () => {
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
    });

    it("refuses a box that is not wholly on the page", () => {
        const page = {
            bounds: boundsOfBox({ x: 0, y: 0, w: 1000, h: 500 }),
            served: { w: 4000, h: 2000 },
        };
        expect(
            captureRegion({ x: 900, y: 450, w: 300, h: 100 }, page),
        ).toBeNull();
        expect(
            captureRegion({ x: -20, y: 10, w: 100, h: 100 }, page),
        ).toBeNull();
        expect(
            captureRegion({ x: 2000, y: 2000, w: 10, h: 10 }, page),
        ).toBeNull();
        expect(captureRegion({ x: 0, y: 0, w: 1000, h: 500 }, page)).toEqual({
            x: 0,
            y: 0,
            w: 4000,
            h: 2000,
        });
    });

    it("writes the capture URL: the region asked at most at the layer's size, the turn undone", () => {
        const region = { x: 400, y: 800, w: 1200, h: 400 };
        const service = "https://img.example/iiif/p";
        expect(captureUrl(service, region, { w: 600, h: 200 }, 0)).toBe(
            `${service}/400,800,1200,400/600,200/0/default.jpg`,
        );
        expect(captureUrl(service, region, { w: 600, h: 200 }, 2)).toBe(
            `${service}/400,800,1200,400/600,200/180/default.jpg`,
        );
        expect(captureUrl(service, region, { w: 200, h: 600 }, 1)).toBe(
            `${service}/400,800,1200,400/600,200/270/default.jpg`,
        );
        expect(captureUrl(service, region, { w: 200, h: 600 }, 3)).toBe(
            `${service}/400,800,1200,400/600,200/90/default.jpg`,
        );
    });

    it("never asks for more than the region holds", () => {
        const region = { x: 0, y: 0, w: 300, h: 100 };
        expect(captureUrl("https://i/s", region, { w: 2000, h: 1000 }, 0)).toBe(
            "https://i/s/0,0,300,100/300,100/0/default.jpg",
        );
        expect(captureUrl("https://i/s", region, { w: 1000, h: 2000 }, 1)).toBe(
            "https://i/s/0,0,300,100/300,100/270/default.jpg",
        );
    });

    it.each([0, 1, 2, 3] as const)(
        "gives the stored size once the image service has scaled and turned it (quarter %i)",
        (quarter) => {
            const stored = { w: 2000, h: 1000 };
            const odd = quarter % 2 === 1;
            const region = odd
                ? { x: 10, y: 20, w: 2500, h: 5000 }
                : { x: 10, y: 20, w: 5000, h: 2500 };
            const url = captureUrl("https://i/s", region, stored, quarter);
            const [, size, rotation] = url.split("/").slice(-4);
            const [w, h] = size.split(",").map(Number);
            expect(Number(rotation)).toBe(((4 - quarter) % 4) * 90);
            expect(odd ? { w: h, h: w } : { w, h }).toEqual(stored);
        },
    );
});
