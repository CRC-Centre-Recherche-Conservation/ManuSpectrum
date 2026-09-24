import { describe, expect, it } from "vitest";
import { createGettext, useGettext } from "vue3-gettext";

describe("vue3-gettext test double", () => {
    it("chooses the singular or the plural from the count", () => {
        const { $ngettext } = useGettext();
        expect($ngettext("%{n} result", "%{n} results", 1)).toBe("%{n} result");
        expect($ngettext("%{n} result", "%{n} results", 0)).toBe("%{n} results");
        expect($ngettext("%{n} result", "%{n} results", 2)).toBe("%{n} results");
    });

    it("substitutes placeholders and leaves unknown ones", () => {
        const { interpolate } = useGettext();
        expect(interpolate("%{n} of %{ total }", { n: 3, total: 9 })).toBe("3 of 9");
        expect(interpolate("%{missing}", {})).toBe("%{missing}");
    });

    it("returns the text for $pgettext and keeps the real createGettext", () => {
        const { $pgettext } = useGettext();
        expect($pgettext("explorer", "Corpus")).toBe("Corpus");
        expect(typeof createGettext).toBe("function");
    });
});
