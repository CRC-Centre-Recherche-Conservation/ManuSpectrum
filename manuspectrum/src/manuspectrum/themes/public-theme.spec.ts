// @vitest-environment node
//
// jsdom replaces the global URL constructor; Node's fileURLToPath then
// rejects the jsdom instance it receives from `new URL(...)`. This file
// touches no DOM, so it runs under the real Node environment instead.
import fs from "fs";
import { fileURLToPath } from "url";
import { describe, expect, it } from "vitest";

import {
    PUBLIC_INK,
    PUBLIC_THEME,
} from "@/manuspectrum/themes/public-theme.ts";

const CHROME = fileURLToPath(
    new URL("../../../media/css/_ms-chrome.scss", import.meta.url),
);
const HEADER_Z_INDEX = 1002;

describe("public theme", () => {
    it("uses the chrome's ink as the primary colour", () => {
        const source = fs.readFileSync(CHROME, "utf-8");
        const ink = /--ink:\s*(#[0-9a-fA-F]{6})\s*;/.exec(source);
        expect(ink?.[1].toLowerCase()).toBe(PUBLIC_INK);
    });

    it("never switches to dark mode and stays out of CSS layers", () => {
        expect(PUBLIC_THEME.theme.options.darkModeSelector).toBe("none");
        expect(PUBLIC_THEME.theme.options.cssLayer).toBe(false);
    });

    it("stacks overlays above the site header", () => {
        expect(PUBLIC_THEME.zIndex?.modal).toBeGreaterThan(HEADER_Z_INDEX);
        expect(PUBLIC_THEME.zIndex?.overlay).toBeGreaterThan(HEADER_Z_INDEX);
        expect(PUBLIC_THEME.zIndex?.tooltip).toBeGreaterThan(HEADER_Z_INDEX);
    });
});
