import { describe, expect, it } from "vitest";

import {
    formatDateRange,
    formatProductionDate,
    formatSize,
    safeHref,
    sameText,
    toRoman,
} from "@/manuspectrum/pages/AnalysisExplorer/format.ts";

describe("format", () => {
    it("writes a file size in the page language", () => {
        expect(formatSize(42_000, "en")).toBe("42 kB");
        expect(formatSize(4_200, "en")).toBe("4.2 kB");
        expect(formatSize(null, "en")).toBe("");
    });

    it("writes a date or a range", () => {
        expect(formatDateRange({ start: "2023-05-02", end: null })).toBe(
            "2023-05-02",
        );
        expect(
            formatDateRange({ start: "2023-05-02", end: "2023-05-04" }),
        ).toBe("2023-05-02 – 2023-05-04");
        expect(formatDateRange({ start: null, end: null })).toBe("");
    });
});

const FRENCH: Record<string, string> = {
    "c. %{year}": "vers %{year}",
    "from %{year}": "à partir de %{year}",
    "from c. %{year}": "à partir de vers %{year}",
    "until %{year}": "jusqu'en %{year}",
    "until c. %{year}": "jusque vers %{year}",
    "%{century} century": "%{century} siècle",
    "%{from} – %{to} c.": "%{from} – %{to} s.",
    "1st half of the %{century} c.": "1re moitié du %{century} s.",
    "2nd half of the %{century} c.": "2e moitié du %{century} s.",
    "1st quarter of the %{century} c.": "1er quart du %{century} s.",
    "2nd quarter of the %{century} c.": "2e quart du %{century} s.",
    "3rd quarter of the %{century} c.": "3e quart du %{century} s.",
    "4th quarter of the %{century} c.": "4e quart du %{century} s.",
    "c. %{start} – %{end}": "vers %{start} – %{end}",
};

function interpolate(
    text: string,
    context: Record<string, string | number>,
): string {
    return text.replace(/%\{(\w+)\}/g, (_, key: string) =>
        String(context[key]),
    );
}

function produced(
    lang: "en" | "fr",
    start: string | null,
    end: string | null,
    approximate = false,
): string {
    const gettext = (msgid: string) =>
        lang === "fr" ? FRENCH[msgid] ?? msgid : msgid;
    return formatProductionDate(
        { start, end, approximate },
        gettext,
        interpolate,
        lang,
    );
}

describe("toRoman", () => {
    it("writes centuries in Roman numerals", () => {
        expect([1, 4, 9, 14, 15, 19, 21].map(toRoman)).toEqual([
            "I",
            "IV",
            "IX",
            "XIV",
            "XV",
            "XIX",
            "XXI",
        ]);
    });
});

describe("formatProductionDate", () => {
    it.each([
        ["en", "1464-05-02", "1464-12", false, "1464"],
        ["fr", "1464-05-02", "1464-12", false, "1464"],
        ["en", "1464", "1464", true, "c. 1464"],
        ["fr", "1464", "1464", true, "vers 1464"],
        ["en", "1401-01", "1500-12", false, "15th century"],
        ["fr", "1401-01", "1500-12", false, "XVe siècle"],
        ["fr", "1401", "1500", true, "XVe siècle"],
        ["en", "1301", "1500", false, "14th – 15th c."],
        ["fr", "1301", "1500", false, "XIVe – XVe s."],
        ["en", "1401", "1450", false, "1st half of the 15th c."],
        ["fr", "1401", "1450", false, "1re moitié du XVe s."],
        ["en", "1451", "1500", false, "2nd half of the 15th c."],
        ["fr", "1451", "1500", false, "2e moitié du XVe s."],
        ["en", "1426", "1450", false, "2nd quarter of the 15th c."],
        ["fr", "1426", "1450", false, "2e quart du XVe s."],
        ["fr", "1401", "1425", false, "1er quart du XVe s."],
        ["en", "1476", "1500", true, "4th quarter of the 15th c."],
        ["en", "1455", "1465", false, "1455 – 1465"],
        ["fr", "1455", "1465", false, "1455 – 1465"],
        ["en", "1455", "1465", true, "c. 1455 – 1465"],
        ["fr", "1455", "1465", true, "vers 1455 – 1465"],
        ["en", "1455-03", null, false, "from 1455"],
        ["fr", "1455", null, false, "à partir de 1455"],
        ["en", null, "1465", false, "until 1465"],
        ["fr", null, "1465", false, "jusqu'en 1465"],
        ["en", null, "1465", true, "until c. 1465"],
        ["fr", "1455", null, true, "à partir de vers 1455"],
        ["en", "1101", "1200", false, "12th century"],
        ["en", "2001", "2100", false, "21st century"],
        ["en", "0101", "0200", false, "2nd century"],
        ["fr", "0001", "0100", false, "Ier siècle"],
        ["en", null, null, false, ""],
    ] as const)(
        "%s: %s – %s (approximate %s) reads « %s »",
        (lang, start, end, approximate, expected) => {
            expect(produced(lang, start, end, approximate)).toBe(expected);
        },
    );
});

describe("safeHref", () => {
    it("keeps an http or https address", () => {
        expect(safeHref("https://example.org/a?b=1")).toBe(
            "https://example.org/a?b=1",
        );
        expect(safeHref("http://example.org/")).toBe("http://example.org/");
    });

    it("turns a bare DOI into its resolver address", () => {
        expect(safeHref("10.5281/zenodo.123")).toBe(
            "https://doi.org/10.5281/zenodo.123",
        );
    });

    it("keeps a path of this site", () => {
        expect(safeHref("/en/report/1")).toBe("/en/report/1");
        expect(safeHref(" /files/x.csv?download=1")).toBe(
            "/files/x.csv?download=1",
        );
    });

    it("refuses any other scheme, another host, a relative path and an empty value", () => {
        expect(safeHref("javascript:alert(1)")).toBeNull();
        expect(safeHref(" JavaScript:alert(1)")).toBeNull();
        expect(safeHref("data:text/html,<script>alert(1)</script>")).toBeNull();
        expect(safeHref("//evil.example/x")).toBeNull();
        expect(safeHref("/\\evil.example/x")).toBeNull();
        expect(safeHref("files/x.csv")).toBeNull();
        expect(safeHref("")).toBeNull();
        expect(safeHref(null)).toBeNull();
        expect(safeHref(undefined)).toBeNull();
    });
});

describe("sameText", () => {
    it("folds case, accents and whitespace", () => {
        expect(sameText("450 nm", " 450  NM ")).toBe(true);
        expect(sameText("Cu Lα", "cu lα")).toBe(true);
        expect(sameText("Pb", "Pb")).toBe(true);
    });

    it("tells two different texts apart", () => {
        expect(sameText("Cu", "MS59-f13v-deconv_Cu")).toBe(false);
    });
});
