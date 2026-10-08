import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent, ref, shallowRef } from "vue";

import { useXrfLens } from "@/manuspectrum/pages/AnalysisExplorer/composables/useXrfLens.ts";
import { reloadXrfSettings } from "@/manuspectrum/pages/AnalysisExplorer/composables/useXrfSettings.ts";
import {
    ANNOUNCE_KEY,
    LINKED_SELECTION_KEY,
    SYNTHESIS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    analysisNode,
    elementNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { shapesKey } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/lens-shapes.ts";

import type { VueWrapper } from "@vue/test-utils";
import type {
    CharacterizationSummary,
    RankedValue,
    SynthesisResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    LensCurve,
    LensLabels,
    XrfLens,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useXrfLens.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { LensShape } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/lens-shapes.ts";
import type { PlotTheme } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

const THEME: PlotTheme = {
    series: Array.from({ length: 12 }, (_, index) => `#s${index}`),
    focus: ["#f1", "#f2", "#f3", "#f4"],
    context: "#999999",
    ink: "#000000",
    inkMuted: "#444444",
    border: "#eeeeee",
    borderHover: "#dddddd",
    background: "#ffffff",
    surface: "#ffffff",
    fontBody: "Sora",
    fontMono: "JetBrains Mono",
};

const ANALYSIS = "11111111-1111-4111-8111-111111111111";
const MATERIAL = "33333333-3333-4333-8333-333333333333";
const HG_ID = "value-hg";
const MAJOR: RankedValue = {
    id: "level-major",
    uri: "level-major",
    label: { value: "major", lang: "en" },
    rank: 0,
};

/** 0.5 to 25 keV in 0.05 steps, flat. */
const ENERGIES = Array.from({ length: 491 }, (_, index) => 0.5 + index * 0.05);
const COUNTS = ENERGIES.map(() => 10);

function curve(overrides: Partial<LensCurve> = {}): LensCurve {
    return {
        xrf: true,
        analysis: ANALYSIS,
        analysisName: "Analysis",
        slot: 0,
        order: 0,
        x: ENERGIES,
        rawY: COUNTS,
        extent: { min: ENERGIES[0], max: ENERGIES.at(-1)!, count: 491 },
        excitation: null,
        ...overrides,
    };
}

const SYNTHESIS = {
    materials: [
        {
            id: MATERIAL,
            evidence: [ANALYSIS],
            canvases: [],
            objects: [],
            selected: false,
            summary: {
                id: MATERIAL,
                name: { value: "Vermilion", lang: "en" },
                elements: [
                    {
                        level: MAJOR,
                        values: [
                            {
                                id: HG_ID,
                                uri: HG_ID,
                                label: { value: "Hg", lang: "en" },
                            },
                        ],
                    },
                ],
            } as unknown as CharacterizationSummary,
        },
    ],
} as unknown as SynthesisResponse;

interface Harness {
    lens: XrfLens;
    wrapper: VueWrapper;
    slots: { value: (NodeId | null)[] };
    previewing: { value: NodeId | null };
    previewSlot: { value: number | null };
    curves: { value: LensCurve[] };
    hidden: { value: boolean[] };
    layout: { value: "overlay" | "multiples" | "offset" };
}

let harness: Harness | null = null;
const announce = vi.fn();

/** Counts on 0.5–25 keV: a flat 10 plus one peak of 5000 at 7 keV. */
const PEAKED = ENERGIES.map(
    (e) => 10 + Math.round(5000 * Math.exp(-((e - 7) ** 2) / (2 * 0.05 ** 2))),
);

async function mountLens(
    start: LensCurve[],
    synthesis: SynthesisResponse | null = null,
    labels?: LensLabels,
): Promise<Harness> {
    const slots = ref<(NodeId | null)[]>([]);
    const previewing = ref<NodeId | null>(null);
    const previewSlot = ref<number | null>(null);
    const curves = shallowRef(start);
    const hidden = ref(start.map(() => false));
    const layout = ref<"overlay" | "multiples" | "offset">("overlay");
    const linked = {
        slots,
        previewing,
        previewSlot,
        graph: ref({ symbols: new Map([[HG_ID, "Hg"]]) }),
    } as unknown as LinkedSelection;
    let lens!: XrfLens;
    const Host = defineComponent({
        setup() {
            lens = useXrfLens({
                curves: () => curves.value,
                hidden: () => hidden.value,
                layout: () => layout.value,
                slots: () => [...new Set(curves.value.map((c) => c.slot))],
                labels: labels ? () => labels : undefined,
            });
            return () => null;
        },
    });
    const wrapper = mount(Host, {
        global: {
            provide: {
                [LINKED_SELECTION_KEY as symbol]: linked,
                [SYNTHESIS_KEY as symbol]: ref(synthesis),
                [ANNOUNCE_KEY as symbol]: announce,
            },
        },
    });
    harness = {
        lens,
        wrapper,
        slots,
        previewing,
        previewSlot,
        curves,
        hidden,
        layout,
    };
    await flushPromises();
    if (start.some((entry) => entry.xrf)) {
        await vi.waitFor(() => expect(lens.table.value).not.toBeNull());
    }
    return harness;
}

function shapesOf(lens: XrfLens): LensShape[] {
    return lens.shapes(THEME);
}

function lineAt(shapes: LensShape[], energy: number): LensShape | undefined {
    return shapes.find(
        (shape) =>
            shape.type === "line" &&
            Math.abs((shape.x0 as number) - energy) < 0.001,
    );
}

beforeEach(() => {
    announce.mockClear();
    setActivePinia(createPinia());
    localStorage.clear();
    reloadXrfSettings();
});

afterEach(() => {
    harness?.wrapper.unmount();
    harness = null;
    localStorage.clear();
});

describe("useXrfLens", () => {
    it("stays silent and loads no line table outside an XRF window", async () => {
        const { lens } = await mountLens([curve({ xrf: false })]);
        expect(lens.active.value).toBe(false);
        expect(lens.table.value).toBeNull();
        expect(shapesOf(lens)).toEqual([]);
    });

    it("draws a pinned element's lines in its slot's hue, inside the data range only", async () => {
        const { lens, slots } = await mountLens([curve()]);
        slots.value = [null, elementNode("Pb")];
        const shapes = shapesOf(lens);
        const alpha = lineAt(shapes, 10.551);
        expect(alpha?.line?.color).toBe("#f2");
        expect(alpha?.xref).toBe("x");
        expect(alpha?.yref).toBe("y domain");
        expect(lineAt(shapes, 74.97)).toBeUndefined();
        expect(
            shapes.every(
                (shape) =>
                    shape.type !== "line" ||
                    ((shape.x0 as number) >= 0.5 && (shape.x0 as number) <= 25),
            ),
        ).toBe(true);
        expect(lens.drawnSymbols.value).toEqual(["Pb"]);
    });

    it("keeps the lines the tube can excite when every curve has a voltage", async () => {
        const { lens, slots, curves } = await mountLens([
            curve({ excitation: { anode: null, kV: 5, source: "conditions" } }),
        ]);
        slots.value = [elementNode("Cu")];
        expect(lineAt(shapesOf(lens), 8.046)).toBeUndefined();
        curves.value = [
            curve({
                excitation: { anode: null, kV: 40, source: "conditions" },
            }),
        ];
        expect(lineAt(shapesOf(lens), 8.046)).toBeDefined();
    });

    it("draws a lens element in ink without touching the focus, and forgets it when removed", async () => {
        const { lens, slots } = await mountLens([curve()]);
        lens.addElement("Fe");
        const shapes = shapesOf(lens);
        expect(lineAt(shapes, 6.405)?.line?.color).toBe("#000000");
        expect(slots.value).toEqual([]);
        expect(lens.settings.value.elements).toEqual(["Fe"]);
        expect(lens.stripElements.value.map((entry) => entry.kind)).toEqual([
            "lens",
        ]);
        lens.removeElement("Fe");
        expect(lineAt(shapesOf(lens), 6.405)).toBeUndefined();
    });

    it("draws a lens element that is also pinned once, in the focus hue", async () => {
        const { lens, slots } = await mountLens([curve()]);
        lens.addElement("Fe");
        slots.value = [elementNode("Fe")];
        const matches = shapesOf(lens).filter(
            (shape) =>
                shape.type === "line" &&
                Math.abs((shape.x0 as number) - 6.405) < 0.001,
        );
        expect(matches).toHaveLength(1);
        expect(matches[0].line?.color).toBe("#f1");
    });

    it("draws a previewed element thin and dashed", async () => {
        const { lens, previewing, previewSlot } = await mountLens([curve()]);
        previewing.value = elementNode("Cu");
        previewSlot.value = 3;
        const shape = lineAt(shapesOf(lens), 8.046);
        expect(shape?.line?.color).toBe("#f3");
        expect(shape?.line?.dash).toBe("dash");
        expect(shape?.line?.width).toBe(1);
        expect(lens.stripElements.value[0]).toMatchObject({
            kind: "preview",
            slot: 3,
        });
    });

    it("marks an element outside the line table as unknown, with nothing drawn", async () => {
        const { lens, slots } = await mountLens([curve()]);
        slots.value = [elementNode("O")];
        expect(shapesOf(lens)).toEqual([]);
        expect(lens.stripElements.value[0]).toMatchObject({
            symbol: "O",
            known: false,
            lines: [],
        });
        expect(lens.drawnSymbols.value).toEqual([]);
    });

    it("ticks the principal line of each element the Selection declares on a visible curve", async () => {
        const { lens, hidden } = await mountLens([curve()], SYNTHESIS);
        const tick = lineAt(shapesOf(lens), 9.989);
        expect(tick?.ysizemode).toBe("pixel");
        expect(tick?.line?.dash).toBe("solid");
        expect(lens.declaredSlots.value).toEqual([
            {
                slot: 0,
                items: [{ symbol: "Hg", level: MAJOR.label }],
            },
        ]);
        hidden.value = [true];
        expect(lineAt(shapesOf(lens), 9.989)).toBeUndefined();
        lens.layers.value = { ...lens.layers.value, declared: false };
        hidden.value = [false];
        expect(lineAt(shapesOf(lens), 9.989)).toBeUndefined();
    });

    it("draws the tube's lines and the Compton band of a curve with a known anode, in the curve's hue", async () => {
        const { lens } = await mountLens([
            curve({
                order: 2,
                excitation: { anode: "Ag", kV: 40, source: "conditions" },
            }),
        ]);
        const shapes = shapesOf(lens);
        const rayleigh = lineAt(shapes, 22.163);
        expect(rayleigh?.line?.color).toBe("#s2");
        expect(rayleigh?.label?.text).toContain("Ag");
        expect(shapes.some((shape) => shape.type === "rect")).toBe(true);
    });

    it("takes the anode of the settings when the conditions give none, and draws nothing for « none »", async () => {
        const { lens } = await mountLens([curve()]);
        expect(lineAt(shapesOf(lens), 22.163)).toBeUndefined();
        lens.setAnode(ANALYSIS, "Ag");
        expect(lineAt(shapesOf(lens), 22.163)).toBeDefined();
        lens.setAnode(ANALYSIS, "none");
        expect(lineAt(shapesOf(lens), 22.163)).toBeUndefined();
        expect(lens.anodeRows.value[0]).toMatchObject({
            analysis: ANALYSIS,
            inferred: null,
            chosen: "none",
        });
    });

    it("draws no instrument peak when the layer is off", async () => {
        const { lens } = await mountLens([
            curve({
                excitation: { anode: "Ag", kV: 40, source: "conditions" },
            }),
        ]);
        lens.layers.value = { ...lens.layers.value, instrument: false };
        expect(shapesOf(lens)).toEqual([]);
    });

    it("tells apart the overlapping lines of two pinned elements, with a band", async () => {
        const { lens, slots } = await mountLens([curve()]);
        slots.value = [elementNode("Pb"), elementNode("As")];
        const [note] = lens.overlapNotes.value;
        expect(note.a).toMatchObject({ symbol: "Pb", label: "Lα1" });
        expect(note.b).toMatchObject({ symbol: "As", label: "Kα1" });
        expect(note.apartA).toMatchObject({ symbol: "Pb", label: "Lβ1" });
        expect(note.apartB).toMatchObject({ symbol: "As", label: "Kβ1" });
        expect(shapesOf(lens).some((shape) => shape.type === "rect")).toBe(
            true,
        );
        lens.layers.value = { ...lens.layers.value, overlaps: false };
        expect(lens.overlapNotes.value).toEqual([]);
    });

    it("keeps the same shapes when the focus gains a node that is not an element", async () => {
        const { lens, slots } = await mountLens([curve()], SYNTHESIS);
        slots.value = [elementNode("Pb")];
        const before = shapesKey(shapesOf(lens));
        slots.value = [elementNode("Pb"), analysisNode(ANALYSIS)];
        expect(shapesKey(shapesOf(lens))).toBe(before);
    });

    it("draws each panel of small multiples on its own axes, inside its own extent", async () => {
        const first = curve();
        const second = curve({
            slot: 1,
            order: 1,
            extent: { min: 10, max: 12, count: 5 },
        });
        const { lens, slots, layout } = await mountLens([first, second]);
        layout.value = "multiples";
        slots.value = [elementNode("Pb")];
        const shapes = shapesOf(lens);
        const second10 = shapes.find(
            (shape) =>
                shape.type === "line" &&
                shape.xref === "x2" &&
                Math.abs((shape.x0 as number) - 10.551) < 0.001,
        );
        expect(second10?.yref).toBe("y2 domain");
        expect(
            shapes.some(
                (shape) =>
                    shape.xref === "x2" && (shape.x0 as number) > 12.0001,
            ),
        ).toBe(false);
    });

    it("saves the anode, the detector and the lens elements in the layout, and reads them back", async () => {
        const { lens } = await mountLens([curve()]);
        lens.setAnode(ANALYSIS, "Rh");
        lens.setDetector("si-pin");
        lens.addElement("Fe");
        reloadXrfSettings();
        expect(lens.settings.value).toEqual({
            detector: "si-pin",
            anodes: { [ANALYSIS]: "Rh" },
            elements: ["Fe"],
        });
        lens.setAnode(ANALYSIS, null);
        lens.setDetector("sdd");
        lens.removeElement("Fe");
        expect(localStorage.getItem("ms-explorer-layout-v1")).toBeNull();
    });

    it("names the instrument ticks and the Compton band in English unless given labels", async () => {
        const source = {
            rawY: PEAKED,
            excitation: { anode: "Ag", kV: 20, source: "conditions" as const },
        };
        const { lens } = await mountLens([curve(source)]);
        const texts = (shapes: LensShape[]) =>
            shapes.flatMap((shape) => (shape.label ? [shape.label.text] : []));
        expect(texts(shapesOf(lens))).toEqual(
            expect.arrayContaining(["Compton", "esc", "sum", "20 kV"]),
        );
        harness?.wrapper.unmount();
        const translated = await mountLens([curve(source)], null, {
            compton: "Comptonfr",
            escape: "échap",
            sum: "somme",
            voltage: (kV) => `${kV} kVfr`,
            elementsFull: "",
            anodesFull: "",
        });
        const french = texts(shapesOf(translated.lens));
        expect(french).toEqual(
            expect.arrayContaining(["Comptonfr", "échap", "somme", "20 kVfr"]),
        );
        expect(french).not.toContain("esc");
    });

    it("announces a refusal at the caps of lens elements and anode choices", async () => {
        const { lens } = await mountLens([curve()]);
        const symbols = lens.symbols.value.slice(0, 31);
        symbols.slice(0, 30).forEach((symbol) => lens.addElement(symbol));
        expect(announce).not.toHaveBeenCalled();
        expect(lens.addElement(symbols[30])).toBe(false);
        expect(lens.toggleElement(symbols[30])).toBe(false);
        expect(announce).toHaveBeenCalledTimes(2);
        expect(announce).toHaveBeenLastCalledWith(
            "The lens holds no more elements",
        );
        announce.mockClear();
        lens.addElement(symbols[0]);
        expect(announce).not.toHaveBeenCalled();
        for (let index = 0; index < 200; index += 1) {
            lens.setAnode(`analysis-${index}`, "Rh");
        }
        expect(announce).not.toHaveBeenCalled();
        lens.setAnode("analysis-200", "Rh");
        expect(announce).toHaveBeenCalledWith(
            "No more anode choices can be kept",
        );
    });
});
