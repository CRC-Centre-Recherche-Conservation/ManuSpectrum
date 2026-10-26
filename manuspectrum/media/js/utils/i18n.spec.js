import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("arches", () => ({
    default: { translations: { greeting: "Bonjour {name}", empty: "" } },
}));

import { isSingular, t, tv } from "./i18n";

describe("t and tv", () => {
    it("reads the page catalogue and falls back to the English source", () => {
        expect(t("greeting", "Hello {name}")).toBe("Bonjour {name}");
        expect(t("missing", "Hello")).toBe("Hello");
        expect(t("empty", "Hello")).toBe("Hello");
    });

    it("fills known placeholders and leaves unknown ones as written", () => {
        expect(tv("greeting", "Hello {name}", { name: "Ada" })).toBe("Bonjour Ada");
        expect(tv("missing", "{n} of {total}", { n: 2 })).toBe("2 of {total}");
        expect(tv("missing", "{n} left")).toBe("{n} left");
    });
});

describe("isSingular", () => {
    afterEach(() => {
        document.documentElement.lang = "";
    });

    it.each([
        ["en", 0, false],
        ["en", 1, true],
        ["en", 2, false],
        ["fr", 0, true],
        ["fr", 1, true],
        ["fr", 2, false],
        ["", 0, false],
        ["not a tag!", 1, true],
        ["not a tag!", 0, false],
    ])("lang %j, n = %i → %s", (lang, n, expected) => {
        document.documentElement.lang = lang;
        expect(isSingular(n)).toBe(expected);
    });
});
