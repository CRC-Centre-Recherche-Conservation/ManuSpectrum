import { describe, expect, it } from "vitest";

import {
    followLiveUnit,
    liveFor,
    unitKey,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/live-unit.ts";

import type { ZoneUnit } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LayerFrame } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import type { PageLayer } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";

const UNIT: ZoneUnit = { x: 16, y: 16, read: true };

function pageOf(frame: Promise<LayerFrame | null>): PageLayer {
    return { layer: {} as PageLayer["layer"], remove: () => undefined, frame };
}

describe("liveFor", () => {
    it("keeps the reported unit for the canvas it was read on only", () => {
        expect(liveFor("c1", { canvas: "c1", unit: UNIT })).toBe(UNIT);
        expect(liveFor("c2", { canvas: "c1", unit: UNIT })).toBeNull();
        expect(liveFor(null, { canvas: "c1", unit: UNIT })).toBeNull();
        expect(liveFor("c1", null)).toBeNull();
    });
});

describe("unitKey", () => {
    it("is the same for units that agree on x and y", () => {
        expect(unitKey({ x: 16, y: 8, read: true })).toBe(
            unitKey({ x: 16, y: 8, read: false }),
        );
        expect(unitKey(UNIT)).not.toBe(unitKey({ x: 16, y: 8, read: true }));
        expect(unitKey(null)).toBe("");
    });
});

describe("followLiveUnit", () => {
    const canvas = { width: 100, height: 100 };

    it("reports the unit of a current page", async () => {
        const seen: (ZoneUnit | null)[] = [];
        await followLiveUnit(
            pageOf(Promise.resolve({ zoom: 4, width: 100, height: 100 })),
            canvas,
            () => true,
            (unit) => seen.push(unit),
        );
        expect(seen).toEqual([UNIT]);
    });

    it("ignores the frame of a page that is no longer the current one, even when it answers last", async () => {
        let current = "a";
        const seen: (ZoneUnit | null)[] = [];
        let answerA: (frame: LayerFrame | null) => void = () => undefined;
        const a = followLiveUnit(
            pageOf(new Promise((resolve) => (answerA = resolve))),
            canvas,
            () => current === "a",
            (unit) => seen.push(unit),
        );
        current = "b";
        const b = followLiveUnit(
            pageOf(Promise.resolve({ zoom: 5, width: 100, height: 100 })),
            canvas,
            () => current === "b",
            (unit) => seen.push(unit),
        );
        await b;
        answerA({ zoom: 4, width: 100, height: 100 });
        await a;
        expect(seen).toEqual([{ x: 32, y: 32, read: true }]);
    });
});
