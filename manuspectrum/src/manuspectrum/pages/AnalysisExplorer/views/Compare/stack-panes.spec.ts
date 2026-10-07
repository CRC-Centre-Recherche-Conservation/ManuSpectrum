import { describe, expect, it } from "vitest";

import {
    applyAppearance,
    paneFilter,
    stackAppearances,
    tintMatrix,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/stack-panes.ts";

import type { StackLayer } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

function layer(
    canvas: string,
    overrides: Partial<StackLayer> = {},
): StackLayer {
    return { canvas, opacity: 100, on: true, tint: null, ...overrides };
}

const NO_FILTER = "";
const TINT_ID = (canvas: string): string | null =>
    canvas === "c" ? null : `f-${canvas}`;

describe("tintMatrix", () => {
    it("maps the luminance of the image to the hue and keeps the alpha", () => {
        const values = tintMatrix([255, 0, 0]).split(/\s+/).map(Number);
        expect(values).toHaveLength(20);
        expect(values.slice(0, 5)).toEqual([0.2126, 0.7152, 0.0722, 0, 0]);
        expect(values.slice(5, 10)).toEqual([0, 0, 0, 0, 0]);
        expect(values.slice(15, 20)).toEqual([0, 0, 0, 1, 0]);
    });
});

describe("paneFilter", () => {
    it("joins the pane's adjustments and the hue filter, either missing", () => {
        expect(paneFilter("brightness(1.5)", "f-a")).toBe(
            "brightness(1.5) url(#f-a)",
        );
        expect(paneFilter("", "f-a")).toBe("url(#f-a)");
        expect(paneFilter("contrast(2)", null)).toBe("contrast(2)");
        expect(paneFilter("", null)).toBe("");
    });
});

describe("stackAppearances", () => {
    it("lets the first shown layer lie normally and blends the others with screen", () => {
        const result = stackAppearances(
            [layer("a", { on: false }), layer("b"), layer("c")],
            { filter: NO_FILTER, tintId: TINT_ID },
        );
        expect(result.get("a")?.blend).toBe(false);
        expect(result.get("b")?.blend).toBe(false);
        expect(result.get("c")?.blend).toBe(true);
    });

    it("orders the panes as the stack, hides the hidden and turns opacity into a fraction", () => {
        const result = stackAppearances(
            [layer("a", { opacity: 40 }), layer("b", { on: false })],
            { filter: "brightness(1.2)", tintId: TINT_ID },
        );
        expect(result.get("a")).toEqual({
            order: 0,
            shown: true,
            opacity: 0.4,
            blend: false,
            filter: "brightness(1.2) url(#f-a)",
        });
        expect(result.get("b")?.order).toBe(1);
        expect(result.get("b")?.shown).toBe(false);
    });
});

describe("applyAppearance", () => {
    it("writes opacity, blend, filter, order and visibility on the pane", () => {
        const pane = document.createElement("div");
        applyAppearance(pane, {
            order: 2,
            shown: true,
            opacity: 0.5,
            blend: true,
            filter: "url(#f-a)",
        });
        expect(pane.style.opacity).toBe("0.5");
        expect(pane.style.getPropertyValue("mix-blend-mode")).toBe("screen");
        expect(pane.style.filter).toBe("url(#f-a)");
        expect(pane.style.zIndex).toBe("402");
        expect(pane.style.display).toBe("");
        applyAppearance(pane, {
            order: 0,
            shown: false,
            opacity: 1,
            blend: false,
            filter: "",
        });
        expect(pane.style.getPropertyValue("mix-blend-mode")).toBe("normal");
        expect(pane.style.display).toBe("none");
    });
});
