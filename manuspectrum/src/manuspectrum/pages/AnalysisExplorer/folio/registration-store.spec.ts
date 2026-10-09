import { describe, expect, it } from "vitest";

import {
    parseRegistrations,
    serializeRegistrations,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/registration-store.ts";

const place = { x: 1, y: 2, w: 3, h: 4 };

describe("registration store", () => {
    it("drops what it cannot trust, entry by entry", () => {
        const raw = JSON.stringify({
            version: 1,
            entries: {
                a: {
                    canvas: "c1",
                    box: place,
                    quarter: 1,
                    capture: null,
                    touched: 5,
                    extra: true,
                },
                b: {
                    canvas: "c1",
                    box: { ...place, w: -3 },
                    quarter: 0,
                    capture: null,
                    touched: 5,
                },
                c: {
                    canvas: "c1",
                    box: place,
                    quarter: 0,
                    touched: 5,
                    capture: {
                        url: "javascript:alert(1)",
                        width: 3,
                        height: 4,
                        canvas: "c1",
                        at: 1,
                    },
                },
                d: {
                    canvas: "c1",
                    box: { ...place, h: Number.NaN },
                    quarter: 0,
                    capture: null,
                    touched: 5,
                },
                e: {
                    canvas: "c1",
                    box: place,
                    quarter: 4,
                    capture: null,
                    touched: 5,
                },
                f: {
                    canvas: "",
                    box: place,
                    quarter: 0,
                    capture: null,
                    touched: 5,
                },
                g: {
                    canvas: "c1",
                    box: place,
                    quarter: 0,
                    touched: 5,
                    capture: {
                        url: "data:image/png;base64,AAAA",
                        width: 3,
                        height: 4,
                        canvas: "c1",
                        at: 1,
                    },
                },
            },
        });
        const entries = parseRegistrations(raw);
        expect(Object.keys(entries)).toEqual(["a", "c", "g"]);
        expect(entries.c.capture).toBeNull();
        expect(entries.g.capture).toBeNull();
        expect("extra" in entries.a).toBe(false);
        expect(parseRegistrations("{")).toEqual({});
        expect(parseRegistrations(null)).toEqual({});
        expect(
            parseRegistrations(JSON.stringify({ version: 2, entries: {} })),
        ).toEqual({});
    });

    it("keeps an http(s) capture", () => {
        const capture = {
            url: "https://img.example/iiif/p/0,0,10,10/10,10/0/default.jpg",
            width: 10,
            height: 10,
            canvas: "c1",
            at: 1,
        };
        const raw = serializeRegistrations({
            a: { canvas: "c1", box: place, quarter: 0, capture, touched: 1 },
        });
        expect(parseRegistrations(raw).a.capture).toEqual(capture);
    });

    describe("capture frame", () => {
        const base = {
            url: "https://img.example/iiif/p/0,0,10,10/10,10/0/default.jpg",
            width: 400,
            height: 200,
            canvas: "c1",
            at: 1,
        };
        const read = (extra: Record<string, unknown>) =>
            parseRegistrations(
                JSON.stringify({
                    version: 1,
                    entries: {
                        a: {
                            canvas: "c1",
                            box: place,
                            quarter: 0,
                            capture: { ...base, ...extra },
                            touched: 1,
                        },
                    },
                }),
            ).a.capture;

        it("keeps a frame inside the layer", () => {
            const frame = { x: 0, y: 50, w: 200, h: 150 };
            expect(read({ frame })).toEqual({ ...base, frame });
        });

        it("reads a capture without a frame as the full frame", () => {
            expect(read({})).toEqual(base);
            expect(read({})).not.toHaveProperty("frame");
        });

        it("drops a frame that is not finite, empty, negative or outside the layer", () => {
            for (const frame of [
                { x: 0, y: 0, w: 0, h: 10 },
                { x: -1, y: 0, w: 10, h: 10 },
                { x: 0, y: 0, w: 401, h: 10 },
                { x: 300, y: 0, w: 200, h: 10 },
                { x: 0, y: 150, w: 10, h: 100 },
                { x: 0, y: 0, w: null, h: 10 },
                { x: "0", y: 0, w: 10, h: 10 },
                "frame",
            ]) {
                expect(read({ frame })).toEqual(base);
            }
        });
    });

    it("keeps the hundred most recently touched", () => {
        const many = Object.fromEntries(
            Array.from({ length: 105 }, (_, n) => [
                `a${n}`,
                {
                    canvas: "c",
                    box: { x: 0, y: 0, w: 1, h: 1 },
                    quarter: 0,
                    capture: null,
                    touched: n,
                },
            ]),
        );
        const kept = parseRegistrations(serializeRegistrations(many as never));
        expect(Object.keys(kept)).toHaveLength(100);
        expect(kept.a0).toBeUndefined();
        expect(kept.a104).toBeDefined();
    });
});
