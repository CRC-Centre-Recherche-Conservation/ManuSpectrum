import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import XrfLensStrip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/XrfLensStrip.vue";

import type {
    StripDeclaredSlot,
    StripElement,
    StripOverlap,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useXrfLens.ts";

const SYMBOLS = ["Na", "Fe", "Cu", "Pb", "U"];
const MAJOR = { value: "major", lang: "en" };
const VERMILION = { value: "Vermilion", lang: "en" };

function element(overrides: Partial<StripElement> = {}): StripElement {
    return {
        symbol: "Pb",
        kind: "pinned",
        slot: 1,
        known: true,
        lines: [
            { label: "Lα1", energy: 10.551 },
            { label: "Lβ1", energy: 12.6143 },
        ],
        declared: null,
        ...overrides,
    };
}

function mountStrip(
    props: {
        elements?: StripElement[];
        declaredSlots?: StripDeclaredSlot[];
        overlaps?: StripOverlap[];
        lensSymbols?: string[];
        symbols?: string[];
    } = {},
) {
    return mount(XrfLensStrip, {
        props: {
            elements: [],
            declaredSlots: [],
            overlaps: [],
            symbols: SYMBOLS,
            lensSymbols: [],
            lang: "en",
            ...props,
        },
    });
}

describe("XrfLensStrip", () => {
    it("lists each element with its lines and energies in the language's number format", () => {
        const view = mountStrip({ elements: [element()] });
        const list = view.find("ul.lines");
        expect(list.attributes("aria-label")).toBe("XRF lines");
        expect(list.find("li").text()).toContain("Lα1 10.55 · Lβ1 12.61 keV");
        const french = mount(XrfLensStrip, {
            props: {
                elements: [element()],
                declaredSlots: [],
                overlaps: [],
                symbols: SYMBOLS,
                lensSymbols: [],
                lang: "fr",
            },
        });
        expect(french.find("li.element").text()).toContain("Lα1 10,55");
    });

    it("says what the Selection declares, with the material's own slot or the slot it cites", () => {
        const view = mountStrip({
            elements: [
                element({
                    declared: {
                        level: MAJOR,
                        material: VERMILION,
                        slot: "A30",
                        cites: ["A3"],
                    },
                }),
                element({
                    symbol: "Hg",
                    slot: 2,
                    declared: {
                        level: null,
                        material: VERMILION,
                        slot: null,
                        cites: ["A3"],
                    },
                }),
            ],
        });
        const texts = view.findAll("li.element .declared").map((n) => n.text());
        expect(texts).toEqual([
            "declared major in Vermilion (A30)",
            "declared in Vermilion (cites A3)",
        ]);
    });

    it("names an element the line table does not hold", () => {
        const view = mountStrip({
            elements: [element({ symbol: "O", known: false, lines: [] })],
        });
        expect(view.find("li.element").text()).toContain(
            "No line in the table for O (Z 11–92)",
        );
    });

    it("says when no line of an element falls in the energy range shown", () => {
        const view = mountStrip({ elements: [element({ lines: [] })] });
        expect(view.find("li.element").text()).toContain(
            "No line in the energy range shown",
        );
    });

    it("writes the overlap and the lines that tell the two apart", () => {
        const view = mountStrip({
            overlaps: [
                {
                    a: { symbol: "Pb", label: "Lα1", energy: 10.551 },
                    b: { symbol: "As", label: "Kα1", energy: 10.544 },
                    apartA: { symbol: "Pb", label: "Lβ1", energy: 12.614 },
                    apartB: { symbol: "As", label: "Kβ1", energy: 11.726 },
                },
                {
                    a: { symbol: "S", label: "Kα1", energy: 2.308 },
                    b: { symbol: "Pb", label: "Mα1", energy: 2.346 },
                    apartA: null,
                    apartB: null,
                },
            ],
        });
        expect(view.findAll("li.overlap").map((n) => n.text())).toEqual([
            "Pb Lα1 10.55 overlaps As Kα1 10.54: tell apart with Pb Lβ1 12.61 vs As Kβ1 11.73",
            "S Kα1 2.31 overlaps Pb Mα1 2.35",
        ]);
    });

    it("lists what each slot declares, best level first", () => {
        const view = mountStrip({
            declaredSlots: [
                {
                    slot: 0,
                    items: [
                        { symbol: "Hg", level: MAJOR },
                        { symbol: "Pb", level: null },
                    ],
                },
            ],
        });
        expect(view.find("li.declared-slot").text()).toBe(
            "Declared on A1: Hg major · Pb",
        );
    });

    it("offers a remove button on lens elements only", async () => {
        const view = mountStrip({
            elements: [
                element(),
                element({ symbol: "Fe", kind: "lens", slot: null }),
            ],
        });
        const removes = view.findAll("button.remove");
        expect(removes).toHaveLength(1);
        expect(removes[0].attributes("aria-label")).toBe("Remove Fe");
        await removes[0].trigger("click");
        expect(view.emitted("remove-element")).toEqual([[{ symbol: "Fe" }]]);
    });

    it("adds the symbol typed in the combobox, offering the table's symbols as options", async () => {
        const view = mountStrip();
        const input = view.find("input");
        expect(input.attributes("role")).toBe("combobox");
        expect(input.attributes("aria-expanded")).toBe("false");
        await input.setValue("p");
        expect(input.attributes("aria-expanded")).toBe("true");
        expect(view.findAll('[role="option"]').map((n) => n.text())).toEqual([
            "Pb",
        ]);
        expect(input.attributes("aria-activedescendant")).toBe(
            view.find('[role="option"]').attributes("id"),
        );
        await input.trigger("keydown", { key: "Enter" });
        expect(view.emitted("add-element")).toEqual([[{ symbol: "Pb" }]]);
        expect((input.element as HTMLInputElement).value).toBe("");
    });

    it("moves through the options with the arrows and closes them with Escape", async () => {
        const view = mountStrip();
        const input = view.find("input");
        await input.trigger("focus");
        await input.setValue("");
        await input.trigger("keydown", { key: "ArrowDown" });
        await input.trigger("keydown", { key: "Enter" });
        expect(view.emitted("add-element")).toEqual([[{ symbol: "Fe" }]]);
        await input.setValue("c");
        expect(input.attributes("aria-expanded")).toBe("true");
        await input.trigger("keydown", { key: "Escape" });
        expect(input.attributes("aria-expanded")).toBe("false");
    });

    it("says so when the symbol typed is not in the line table, and adds nothing", async () => {
        const view = mountStrip();
        const input = view.find("input");
        await input.setValue("Xx");
        await input.trigger("keydown", { key: "Enter" });
        expect(view.emitted("add-element")).toBeUndefined();
        expect(view.find("p.unknown").text()).toBe(
            "No line in the table for Xx (Z 11–92)",
        );
    });

    it("toggles lens elements from a mini periodic table of the table's elements", async () => {
        const view = mountStrip({ lensSymbols: ["Cu"] });
        expect(view.find(".mini-table").exists()).toBe(false);
        const toggle = view.find("button.table-toggle");
        expect(toggle.attributes("aria-expanded")).toBe("false");
        await toggle.trigger("click");
        expect(toggle.attributes("aria-expanded")).toBe("true");
        const cells = view.findAll(".mini-table button.cell");
        expect(cells.map((cell) => cell.text()).sort()).toEqual(
            [...SYMBOLS].sort(),
        );
        const copper = cells.find((cell) => cell.text() === "Cu")!;
        expect(copper.attributes("aria-pressed")).toBe("true");
        expect(copper.attributes("aria-label")).toBe("Cu (Z 29)");
        const iron = cells.find((cell) => cell.text() === "Fe")!;
        expect(iron.attributes("aria-pressed")).toBe("false");
        await iron.trigger("click");
        expect(view.emitted("toggle-element")).toEqual([[{ symbol: "Fe" }]]);
    });

    it("shows no list while the lens has nothing to say", () => {
        expect(mountStrip().find("ul.lines").exists()).toBe(false);
    });
});
