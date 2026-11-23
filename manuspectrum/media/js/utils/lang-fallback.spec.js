import { describe, it, expect } from "vitest";
import "./lang-fallback.js";

const pick = (
    values,
    current = "en",
    languages = [{ code: "en" }, { code: "fr" }],
) =>
    globalThis.msLangFallback(
        values,
        current,
        languages,
        "Not entered in this language, shown in",
    );
const NOTHING = { text: "", code: null, label: "" };

describe("msLangFallback", () => {
    it("the page language wins", () => {
        expect(
            pick({ en: { value: "Initial" }, fr: { value: "Lettrine" } }),
        ).toEqual({
            text: "Initial",
            code: null,
            label: "",
        });
    });

    it("a whitespace page value falls back", () => {
        const picked = pick({ en: { value: "  " }, fr: { value: "Lettrine" } });
        expect(picked.text).toBe("Lettrine");
        expect(picked.code).toBe("fr");
    });

    it("languages are tried in their order", () => {
        const languages = [{ code: "en" }, { code: "fr" }, { code: "de" }];
        expect(
            pick(
                { fr: { value: "" }, de: { value: "Initiale" } },
                "en",
                languages,
            ).code,
        ).toBe("de");
        expect(
            pick(
                { fr: { value: "Lettrine" }, de: { value: "Initiale" } },
                "en",
                languages,
            ).code,
        ).toBe("fr");
        expect(pick({ en: { value: "" }, fr: { value: " " } })).toEqual(
            NOTHING,
        );
    });

    it("anything but a values object fills nothing", () => {
        for (const values of [null, undefined, "plain", ["x"]]) {
            expect(pick(values)).toEqual(NOTHING);
        }
    });

    it("empty, missing or non-array languages leave the page language only", () => {
        const values = { fr: { value: "Lettrine" } };
        for (const languages of [[], undefined, null, "fr", {}]) {
            expect(
                globalThis.msLangFallback(values, "en", languages, "x"),
            ).toEqual(NOTHING);
        }
        expect(
            globalThis.msLangFallback(
                { en: { value: "I" } },
                "en",
                undefined,
                "x",
            ).text,
        ).toBe("I");
    });

    it("the label names the language in the page language", () => {
        expect(
            pick({ en: { value: "" }, fr: { value: "Lettrine" } }).label,
        ).toBe("Not entered in this language, shown in French");
        const french = pick(
            { en: { value: "Initial" }, fr: { value: "" } },
            "fr",
        );
        expect(french.code).toBe("en");
        expect(french.label.endsWith("anglais")).toBe(true);
    });

    it("a number is stringified", () => {
        expect(pick({ en: { value: 0 } }).text).toBe("0");
        expect(pick({ en: { value: 42 } }).text).toBe("42");
    });
});
