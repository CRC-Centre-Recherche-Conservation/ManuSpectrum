import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
    COLOUR_TOKENS,
    FALLBACK_COLOURS,
    FOCUS_TOKENS,
    readColours,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-colours.ts";

describe("the fallbacks", () => {
    const scss = readFileSync(
        `${__dirname}/../../../../../../media/css/_ms-chrome.scss`,
        "utf8",
    );

    it("match the tokens of _ms-chrome.scss", () => {
        expect(scss).toContain("--map-sea: #e4ebf1;");
        expect(scss).toContain("--focus-1: #3d2e8d;");
        for (const [key, token] of Object.entries(COLOUR_TOKENS)) {
            const value = FALLBACK_COLOURS[key as keyof typeof COLOUR_TOKENS];
            expect(scss).toContain(`${token}: ${value};`);
        }
        FOCUS_TOKENS.forEach((token, index) => {
            expect(scss).toContain(
                `${token}: ${FALLBACK_COLOURS.focus[index]};`,
            );
        });
    });
});

describe("readColours", () => {
    it("reads the tokens set on the element", () => {
        const element = document.createElement("div");
        element.style.setProperty("--map-sea", "#010203");
        element.style.setProperty("--focus-3", "#040506");
        document.body.append(element);
        const colours = readColours(element);
        expect(colours.sea).toBe("#010203");
        expect(colours.focus[2]).toBe("#040506");
        expect(colours.land).toBe(FALLBACK_COLOURS.land);
        element.remove();
    });

    it("falls back on an empty token", () => {
        const element = document.createElement("div");
        element.style.setProperty("--blue-text", " ");
        document.body.append(element);
        expect(readColours(element)).toEqual(FALLBACK_COLOURS);
        element.remove();
    });
});
