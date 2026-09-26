import { describe, expect, it } from "vitest";
import { parseContentState } from "@iiif/helpers/content-state";

import {
    analysisContentState,
    miradorLink,
} from "@/manuspectrum/pages/AnalysisExplorer/share/content-state.ts";

import type { Shape } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const MANIFEST =
    "http://testserver/iiif/v3/explorer-manifest?ids=an:x:-&lang=en";
const CANVAS = "https://iiif.example/ms59/canvas/f1v";
const MIRADOR = "https://viewer.example/mirador/";

interface Decoded {
    type: string;
    motivation: string[];
    target:
        | string
        | {
              type: string;
              source: { id: string; type: string; partOf: { id: string }[] };
              selector?: { type: string; value?: string; x?: number };
          };
}

async function decoded(shape: Shape | null): Promise<Decoded> {
    const state = await analysisContentState(MANIFEST, CANVAS, shape);
    expect(state).toMatch(/^[A-Za-z0-9_-]+$/);
    return parseContentState(state) as unknown as Decoded;
}

describe("analysisContentState", () => {
    it("round-trips through decodeContentState", async () => {
        const state = await decoded({ type: "point", x: 10, y: 20 });
        expect(state.type).toBe("Annotation");
        expect(state.motivation).toEqual(["contentState"]);
        const target = state.target as Exclude<Decoded["target"], string>;
        expect(target.source.id).toBe(CANVAS);
        expect(target.source.type).toBe("Canvas");
        expect(target.source.partOf).toEqual([
            { id: MANIFEST, type: "Manifest" },
        ]);
        expect(target.selector).toEqual({
            type: "PointSelector",
            x: 10,
            y: 20,
        });
    });

    it("encodes a point, a rect and a polygon", async () => {
        const rect = (
            await decoded({ type: "rect", x: 1.6, y: 2, w: 30, h: 40 })
        ).target as Exclude<Decoded["target"], string>;
        expect(rect.selector).toEqual({
            type: "FragmentSelector",
            conformsTo: "http://www.w3.org/TR/media-frags/",
            value: "xywh=1,2,30,40",
        });
        const polygon = (
            await decoded({
                type: "polygon",
                points: [
                    [0, 0],
                    [10.2, 0],
                    [10, 10],
                ],
            })
        ).target as Exclude<Decoded["target"], string>;
        expect(polygon.selector).toEqual({
            type: "SvgSelector",
            value: '<svg xmlns="http://www.w3.org/2000/svg"><polygon points="0,0 10,0 10,10"/></svg>',
        });
    });

    it("targets the whole canvas without a shape", async () => {
        const state = await decoded(null);
        expect(state.target).toEqual({
            id: CANVAS,
            type: "Canvas",
            partOf: [{ id: MANIFEST, type: "Manifest" }],
        });
    });
});

function params(link: string | null): URLSearchParams {
    expect(link).not.toBeNull();
    return new URL(link as string).searchParams;
}

describe("miradorLink", () => {
    it("opens a manifest by its URL", () => {
        const link = miradorLink(MIRADOR, { manifest: MANIFEST });
        expect(link?.startsWith(MIRADOR)).toBe(true);
        expect(params(link).get("manifest")).toBe(MANIFEST);
        expect(params(link).has("iiif-content")).toBe(false);
    });

    it("opens a content state as iiif-content", () => {
        const link = miradorLink(MIRADOR, { contentState: "abc_-" });
        expect(params(link).get("iiif-content")).toBe("abc_-");
        expect(params(link).has("manifest")).toBe(false);
    });

    it("keeps the viewer's own query", () => {
        const link = miradorLink("https://viewer.example/?theme=dark", {
            manifest: MANIFEST,
        });
        expect(params(link).get("theme")).toBe("dark");
        expect(params(link).get("manifest")).toBe(MANIFEST);
    });

    it("gives nothing without a viewer or for another scheme", () => {
        expect(miradorLink("", { manifest: MANIFEST })).toBeNull();
        expect(
            miradorLink("javascript:alert(1)", { manifest: MANIFEST }),
        ).toBeNull();
        expect(miradorLink("/relative", { manifest: MANIFEST })).toBeNull();
    });
});
