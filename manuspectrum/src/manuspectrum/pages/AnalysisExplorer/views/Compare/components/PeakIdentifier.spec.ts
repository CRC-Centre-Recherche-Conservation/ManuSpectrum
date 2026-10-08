import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";

import PeakIdentifier from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/PeakIdentifier.vue";

import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

import type { VueWrapper } from "@vue/test-utils";
import type {
    Confirmation,
    ElementCandidate,
    InstrumentCandidate,
    InstrumentKind,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/identify.ts";

let wrapper: VueWrapper | null = null;
const announce = vi.fn();

function line(label: string, energy: number) {
    return { name: label, label, energy, intensity: 1, initial: "L3" };
}

function element(
    symbol: string,
    label: string,
    energy: number,
    confirmations: Confirmation[] = [],
    declared: ElementCandidate["declared"] = null,
): ElementCandidate {
    return {
        type: "element",
        symbol,
        line: line(label, energy),
        delta: 0,
        confirmations,
        score: null,
        declared,
        inLens: false,
    };
}

function instrument(
    kind: InstrumentKind,
    energy: number,
    extra: Partial<InstrumentCandidate["peak"]> = {},
): InstrumentCandidate {
    return {
        type: "instrument",
        delta: 0,
        peak: {
            kind,
            energy,
            from: energy,
            to: energy,
            source: null,
            line: null,
            parents: [],
            ...extra,
        },
    };
}

const PB = element(
    "Pb",
    "Lα1",
    10.55,
    [
        { line: line("Lβ1", 12.61), state: "present" },
        { line: line("Lγ1", 14.76), state: "out-of-range" },
    ],
    { scope: "curve", entry: { rank: 0, materials: [] } },
);
const AS = element("As", "Kα1", 10.54, [
    { line: line("Kβ1", 11.73), state: "absent" },
    { line: line("Kβ3", 11.7), state: "not-excited" },
]);

function mountIdentifier(
    props: Partial<InstanceType<typeof PeakIdentifier>["$props"]> = {},
): VueWrapper {
    wrapper = mount(PeakIdentifier, {
        attachTo: document.body,
        props: {
            energy: 10.55,
            curveName: "A2 · file.csv",
            candidates: [PB, AS],
            kV: 40,
            channel: 0.01,
            tolerance: 0.07,
            lang: "en",
            pinnable: (symbol: string) => symbol === "Pb",
            pinned: () => false,
            lensSymbols: [],
            declaredParts: () => ({
                level: { value: "major", lang: "en" },
                material: { value: "Vermilion", lang: "en" },
                slot: "A30",
                cites: [],
            }),
            ...props,
        },
        global: { provide: { [ANNOUNCE_KEY as symbol]: announce } },
    });
    return wrapper;
}

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    announce.mockClear();
});

describe("PeakIdentifier", () => {
    it("is a non-modal dialog named by its heading, with the spectrum checked and the footer", () => {
        const view = mountIdentifier();
        const section = view.find("section");
        expect(section.attributes("role")).toBe("dialog");
        expect(section.attributes("aria-modal")).toBeUndefined();
        const heading = view.find("h3");
        expect(section.attributes("aria-labelledby")).toBe(
            heading.attributes("id"),
        );
        expect(heading.text()).toBe("Candidates at 10.55 keV (± 0.07)");
        expect(view.find(".checked").text()).toBe(
            "Spectrum checked: A2 · file.csv",
        );
        expect(view.find(".footer").text()).toBe(
            "Indications only: the analyst decides.",
        );
    });

    it("announces the count of candidates when it opens and when the energy moves", async () => {
        const view = mountIdentifier();
        expect(announce).toHaveBeenLastCalledWith("2 candidates at 10.55 keV");
        await view.setProps({ energy: 10.56, candidates: [PB] });
        expect(announce).toHaveBeenLastCalledWith("1 candidate at 10.56 keV");
    });

    it("moves the focus to the energy field when it opens", () => {
        const view = mountIdentifier();
        expect(document.activeElement).toBe(view.find("input").element);
    });

    it("lists an element's line, its confirmations and what the Selection declares", () => {
        const view = mountIdentifier();
        const pb = view.find('li[data-symbol="Pb"]').text();
        expect(pb).toContain("Pb");
        expect(pb).toContain("Lα1 10.55");
        expect(pb).toContain("Lβ1 12.61 present");
        expect(pb).toContain("Lγ1 14.76 out of range");
        expect(pb).toContain("declared major in Vermilion (A30)");
        const arsenic = view.find('li[data-symbol="As"]').text();
        expect(arsenic).toContain("Kβ1 11.73 absent");
        expect(arsenic).toContain("Kβ3 11.70 not excited at 40 kV");
        expect(arsenic).not.toContain("declared");
    });

    it("says an unresolved confirmation is too close to tell, and writes the voltage in the reader's language", () => {
        const close = element("S", "Kα1", 2.31, [
            { line: line("Kβ1", 2.47), state: "unresolved" },
            { line: line("Kβ3", 2.5), state: "not-excited" },
        ]);
        const view = mountIdentifier({
            candidates: [close],
            kV: 12.5,
            lang: "fr",
        });
        const text = view.find('li[data-symbol="S"]').text();
        expect(text).toContain("Kβ1 2,47 too close to tell");
        expect(text).toContain("not excited at 12,5 kV");
    });

    it("lists the instrument peaks", () => {
        const view = mountIdentifier({
            candidates: [
                instrument("rayleigh", 22.16, { source: "Ag", line: "Kα1" }),
                instrument("compton", 21.3, { source: "Ag", line: "Kα1" }),
                instrument("escape", 8.66, { parents: [10.4] }),
                instrument("sum", 12.8, { parents: [6.4, 6.4] }),
                instrument("duane-hunt", 40),
            ],
        });
        expect(view.findAll(".instrument").map((row) => row.text())).toEqual([
            "Ag Kα1 · Rayleigh scatter",
            "Ag Kα1 · Compton scatter",
            "Escape of 10.40 keV",
            "Sum 6.40 + 6.40 keV",
            "Tube voltage limit (40.00 kV)",
        ]);
    });

    it("shows eight candidates, then « Show all (n) »", async () => {
        const many = Array.from({ length: 11 }, (_, index) =>
            instrument("sum", 10 + index, { parents: [5, 5 + index] }),
        );
        const view = mountIdentifier({ candidates: many });
        expect(view.findAll(".candidate")).toHaveLength(8);
        const more = view.find(".show-all");
        expect(more.text()).toBe("Show all (11)");
        await more.trigger("click");
        expect(view.findAll(".candidate")).toHaveLength(11);
        expect(view.find(".show-all").exists()).toBe(false);
    });

    it("says so when nothing is within the tolerance", () => {
        const view = mountIdentifier({ candidates: [] });
        expect(view.find(".none").text()).toBe(
            "No candidate within the tolerance",
        );
    });

    it("steps the field by the channel width and moves one channel with ← and →", async () => {
        const view = mountIdentifier({ channel: 0.0195 });
        const input = view.find("input");
        expect(input.attributes("type")).toBe("number");
        expect(input.attributes("step")).toBe("0.0195");
        await view.find('[data-action="raise"]').trigger("click");
        expect(view.emitted("move")?.at(-1)?.[0]).toEqual({
            energy: 10.5695,
        });
        await view.find('[data-action="lower"]').trigger("click");
        expect(view.emitted("move")?.at(-1)?.[0]).toEqual({
            energy: 10.5305,
        });
        await input.setValue("9.5");
        expect(view.emitted("move")?.at(-1)?.[0]).toEqual({ energy: 9.5 });
        await input.setValue("");
        expect(view.emitted("move")).toHaveLength(3);
    });

    it("offers « Pin Pb » only for an element the focus can hold, and « Show Pb lines » for each", async () => {
        const view = mountIdentifier({
            lensSymbols: ["As"],
            pinned: (s) => s === "Pb",
        });
        const pb = view.find('li[data-symbol="Pb"]');
        const arsenic = view.find('li[data-symbol="As"]');
        expect(pb.find('[data-action="pin"]').text()).toBe("Pin Pb");
        expect(pb.find('[data-action="pin"]').attributes("aria-pressed")).toBe(
            "true",
        );
        expect(arsenic.find('[data-action="pin"]').exists()).toBe(false);
        expect(arsenic.find('[data-action="lines"]').text()).toBe(
            "Show As lines",
        );
        expect(
            arsenic.find('[data-action="lines"]').attributes("aria-pressed"),
        ).toBe("true");
        expect(
            pb.find('[data-action="lines"]').attributes("aria-pressed"),
        ).toBe("false");
        await pb.find('[data-action="pin"]').trigger("click");
        await arsenic.find('[data-action="lines"]').trigger("click");
        expect(view.emitted("toggle-pin")).toEqual([[{ symbol: "Pb" }]]);
        expect(view.emitted("toggle-lens")).toEqual([[{ symbol: "As" }]]);
    });

    it("closes on Escape and pins nothing by itself", async () => {
        const view = mountIdentifier();
        await view.find("input").trigger("keydown", { key: "Escape" });
        expect(view.emitted("close")).toHaveLength(1);
        expect(view.emitted("toggle-pin")).toBeUndefined();
        expect(view.emitted("toggle-lens")).toBeUndefined();
    });

    it("scrolls itself into view, no further than needed, when it opens and when the energy moves", async () => {
        const scroll = vi.fn();
        Element.prototype.scrollIntoView = scroll;
        try {
            const view = mountIdentifier();
            await flushPromises();
            expect(scroll).toHaveBeenCalledWith({ block: "nearest" });
            scroll.mockClear();
            await view.setProps({ energy: 10.56 });
            await flushPromises();
            expect(scroll).toHaveBeenCalledWith({ block: "nearest" });
        } finally {
            delete (Element.prototype as Partial<Element>).scrollIntoView;
        }
    });

    it("focuses the energy field without scrolling the page to it", () => {
        const focus = vi.spyOn(HTMLInputElement.prototype, "focus");
        mountIdentifier();
        expect(focus).toHaveBeenCalledWith({ preventScroll: true });
        focus.mockRestore();
    });
});
