import { describe, expect, it } from "vitest";

import {
    countsName,
    countsText,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/count-labels.ts";

const words = {
    $gettext: (msgid: string) => msgid,
    $ngettext: (singular: string, plural: string, n: number) =>
        n === 1 ? singular : plural,
    interpolate: (message: string, values: Record<string, string | number>) =>
        message.replace(/%\{(\w+)\}/g, (_, key: string) => String(values[key])),
};

describe("count-labels", () => {
    it("shortens the counts, plural-aware", () => {
        expect(countsText(words, 87, 103)).toBe("87 docs · 103 Comp.");
        expect(countsText(words, 1, 1)).toBe("1 doc · 1 Comp.");
        expect(countsText(words, 0, 2)).toBe("0 docs · 2 Comp.");
    });

    it("says the counts in words, plural-aware", () => {
        expect(countsName(words, 87, 103)).toBe("87 documents, 103 Components");
        expect(countsName(words, 1, 1)).toBe("1 document, 1 Component");
    });
});
