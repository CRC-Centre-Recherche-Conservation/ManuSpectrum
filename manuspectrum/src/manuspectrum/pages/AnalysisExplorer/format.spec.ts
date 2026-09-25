import { describe, expect, it } from "vitest";

import {
    formatDateRange,
    formatSize,
    safeHref,
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
