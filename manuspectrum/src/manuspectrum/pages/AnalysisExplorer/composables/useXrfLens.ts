import { computed, inject, onScopeDispose, ref, shallowRef, watch } from "vue";

import { useXrfSettings } from "@/manuspectrum/pages/AnalysisExplorer/composables/useXrfSettings.ts";
import {
    ANNOUNCE_KEY,
    LINKED_SELECTION_KEY,
    SYNTHESIS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    elementNode,
    parseNodeId,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { itemHue } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";
import {
    declaredByAnalysis,
    declaredParts,
    mergeDeclared,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/declared.ts";
import {
    candidates,
    instrumentPeaks,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/identify.ts";
import { lensShapes } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/lens-shapes.ts";
import {
    allSymbols,
    loadLineTable,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/line-table.ts";
import {
    overlaps,
    tellApart,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/overlaps.ts";
import {
    excitable,
    focusLines,
    fwhmAt,
    principalLine,
    tolerance,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/physics.ts";
import {
    channelWidth,
    snapToPeak,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/spectrum.ts";

import type { ShallowRef } from "vue";

import type {
    Excitation,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type {
    XrfAnode,
    XrfDetector,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";
import type {
    Extent,
    WorkshopLayout,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";
import type { PlotTheme } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";
import type {
    DeclaredElement,
    DeclaredMap,
    DeclaredParts,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/declared.ts";
import type {
    Candidate,
    InstrumentPeak,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/identify.ts";
import type {
    FocusLines,
    InstrumentTick,
    EnergyBand,
    LensElementLines,
    LensPanel,
    LensShape,
    OverlapBand,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/lens-shapes.ts";
import type {
    XrfElement,
    XrfLineTable,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/line-table.ts";
import type { LineRef } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/physics.ts";

/** Detector resolution at Mn Kα (keV), by setting. */
const DETECTOR_FWHM_KEV: Record<XrfDetector, number> = {
    sdd: 0.14,
    "si-pin": 0.18,
};
/** Instrument ticks closer than this (keV) are drawn once. */
const TICK_MERGE_KEV = 0.02;
/** Overlap sentences the strip lists at most. */
const MAX_OVERLAP_NOTES = 8;
/** Rank given to a declared element whose material states no level (the weakest). */
const UNRANKED = 2;

/** A drawn curve, as the lens reads it. */
export interface LensCurve {
    /** Whether its file is an XRF spectrum (`isXrfViewer`). */
    xrf: boolean;
    analysis: string;
    analysisName: string;
    slot: number;
    /** Its order in the window: its hue. */
    order: number;
    /** The series as stored: raw energies and counts, the treatment ignored. */
    x: ArrayLike<number>;
    rawY: ArrayLike<number>;
    extent: Extent | null;
    excitation: Excitation | null;
}

export interface LensSources {
    curves: () => readonly LensCurve[];
    /** Whether each curve is hidden (the focus or the legend's eye), in the curves' order. */
    hidden: () => readonly boolean[];
    layout: () => WorkshopLayout;
    /** The slots of the window, in panel order. */
    slots: () => readonly number[];
    labels?: () => LensLabels;
}

/** The words the lens draws or announces, translated by the caller; English when absent. */
export interface LensLabels {
    compton: string;
    escape: string;
    sum: string;
    /** The Duane–Hunt tick: « 40 kV ». */
    voltage: (kV: number) => string;
    /** Said when the lens elements are full. */
    elementsFull: string;
    /** Said when the anode choices are full. */
    anodesFull: string;
}

const ENGLISH_LABELS: LensLabels = {
    compton: "Compton",
    escape: "esc",
    sum: "sum",
    voltage: (kV) => `${kV} kV`,
    elementsFull: "The lens holds no more elements",
    anodesFull: "No more anode choices can be kept",
};

export interface LensLayers {
    declared: boolean;
    instrument: boolean;
    overlaps: boolean;
}

export type ElementKind = "pinned" | "preview" | "lens";

export interface StripLine {
    label: string;
    energy: number;
}

export interface StripElement {
    symbol: string;
    kind: ElementKind;
    /** The focus slot of a pinned or previewed element. */
    slot: number | null;
    /** Whether the line table holds the element (Z 11 to 92). */
    known: boolean;
    lines: StripLine[];
    declared: DeclaredParts | null;
}

export interface StripLineRef {
    symbol: string;
    label: string;
    energy: number;
}

export interface StripOverlap {
    a: StripLineRef;
    b: StripLineRef;
    /** The line each element can be told apart by; null when none does. */
    apartA: StripLineRef | null;
    apartB: StripLineRef | null;
}

export interface StripDeclaredSlot {
    slot: number;
    items: { symbol: string; level: Label | null }[];
}

/** How a curve is excited: the anode and voltage, and whether the conditions gave the anode. */
export interface Excitations {
    anode: string | null;
    kV: number | null;
    inferred: boolean;
}

/** One analysis of the window in the settings menu. */
export interface AnodeRow {
    analysis: string;
    slot: number;
    name: string;
    /** The anode the conditions gave; null when none. */
    inferred: string | null;
    chosen: XrfAnode | "none" | null;
}

interface PanelModel {
    suffix: string;
    extent: [number, number];
    declared: LensPanel["declared"];
    ticks: { curveOrder: number; label: string; energy: number }[];
    bands: { curveOrder: number; label: string; from: number; to: number }[];
}

interface LensModel {
    panels: PanelModel[];
    focus: FocusLines[];
    elements: LensElementLines[];
    overlaps: OverlapBand[];
}

function symbolOf(id: NodeId | null | undefined): string | null {
    if (!id) return null;
    const node = parseNodeId(id);
    return node?.kind === "el" ? node.parts[0] : null;
}

function union(extents: readonly Extent[]): [number, number] | null {
    if (extents.length === 0) return null;
    return [
        Math.min(...extents.map((extent) => extent.min)),
        Math.max(...extents.map((extent) => extent.max)),
    ];
}

function lineRefOf(symbol: string, line: LineRef): StripLineRef {
    return { symbol, label: line.label, energy: line.energy };
}

/**
 * The XRF lens of one XY window: whether the window is an XRF one, the line
 * table (loaded only then), the elements it draws (the pinned and previewed
 * `el:` nodes of the linked selection, the reader's lens elements), what the
 * Selection's materials declare on each curve, the instrument peaks of each
 * curve, the overlaps, and the Plotly shapes and strip text that follow.
 *
 * The lens never touches the focus: `shapes(theme)` is a pure function of its
 * inputs, so an equal key (`shapesKey`) means an equal drawing and no
 * relayout. Lines are kept inside each panel's X extent and, when a tube
 * voltage is known on every curve, to those it can excite. An element of the
 * window's own pins takes its focus hue; a lens element draws in ink and
 * never filters anything.
 */
export function useXrfLens(sources: LensSources) {
    const linked = inject(LINKED_SELECTION_KEY, null);
    const synthesis = inject(SYNTHESIS_KEY, null);
    const store = useExplorerStore();
    const announce = inject(ANNOUNCE_KEY, () => undefined);
    const {
        settings,
        setDetector,
        setAnode: keepAnode,
        addElement: keepElement,
        removeElement,
    } = useXrfSettings();
    const labels = () => sources.labels?.() ?? ENGLISH_LABELS;

    /** Adds a lens element; a refusal for a full list is announced. */
    function addElement(symbol: string): boolean {
        const added = keepElement(symbol);
        if (!added && !settings.value.elements.includes(symbol)) {
            announce(labels().elementsFull);
        }
        return added;
    }

    function toggleElement(symbol: string): boolean {
        if (settings.value.elements.includes(symbol)) {
            removeElement(symbol);
            return false;
        }
        return addElement(symbol);
    }

    function setAnode(analysis: string, anode: XrfAnode | "none" | null): void {
        if (!keepAnode(analysis, anode)) announce(labels().anodesFull);
    }

    const layers = ref<LensLayers>({
        declared: true,
        instrument: true,
        overlaps: true,
    });
    const table: ShallowRef<XrfLineTable | null> = shallowRef(null);
    let disposed = false;

    const active = computed(() => {
        const curves = sources.curves();
        return curves.length > 0 && curves.every((curve) => curve.xrf);
    });
    const fwhmMn = computed(() => DETECTOR_FWHM_KEV[settings.value.detector]);
    const symbols = computed(() =>
        table.value ? allSymbols(table.value) : [],
    );

    const pinned = computed(() =>
        (linked?.slots?.value ?? []).flatMap((id, index) => {
            const symbol = symbolOf(id);
            return symbol ? [{ symbol, slot: index + 1 }] : [];
        }),
    );
    const previewed = computed(() => {
        const symbol = symbolOf(linked?.previewing?.value);
        if (!symbol || pinned.value.some((held) => held.symbol === symbol)) {
            return null;
        }
        return { symbol, slot: linked?.previewSlot?.value ?? null };
    });
    const lensSymbols = computed(() =>
        settings.value.elements.filter(
            (symbol) => !pinned.value.some((held) => held.symbol === symbol),
        ),
    );
    /** The elements whose lines the window draws in full, pinned ones first. */
    const drawnSymbols = computed(() =>
        table.value
            ? [
                  ...pinned.value.map(({ symbol }) => symbol),
                  ...lensSymbols.value,
              ].filter((symbol) => symbol in (table.value?.elements ?? {}))
            : [],
    );

    const declared = computed<DeclaredMap>(() => {
        const graph = linked?.graph?.value;
        const data = synthesis?.value;
        return data && graph
            ? declaredByAnalysis(data, graph.symbols)
            : new Map();
    });
    const declaredOfCurve = (curve: LensCurve) =>
        declared.value.get(curve.analysis);

    const windowRange = computed(() =>
        union(
            sources
                .curves()
                .flatMap((curve) => (curve.extent ? [curve.extent] : [])),
        ),
    );
    /** The highest tube voltage of the window, null when any curve has none (then every line is kept). */
    const windowKv = computed<number | null>(() => {
        const volts = sources.curves().map((curve) => curve.excitation?.kV);
        return volts.length > 0 && volts.every((kV) => typeof kV === "number")
            ? Math.max(...(volts as number[]))
            : null;
    });

    function excitationOf(curve: LensCurve): Excitations {
        const inferred = curve.excitation?.anode ?? null;
        const kV = curve.excitation?.kV ?? null;
        if (inferred) return { anode: inferred, kV, inferred: true };
        const chosen = settings.value.anodes[curve.analysis];
        return {
            anode: chosen && chosen !== "none" ? chosen : null,
            kV,
            inferred: false,
        };
    }

    const anodeRows = computed<AnodeRow[]>(() => {
        const seen = new Set<string>();
        return sources.curves().flatMap((curve) => {
            if (seen.has(curve.analysis)) return [];
            seen.add(curve.analysis);
            return [
                {
                    analysis: curve.analysis,
                    slot: curve.slot,
                    name: curve.analysisName,
                    inferred: curve.excitation?.anode ?? null,
                    chosen: settings.value.anodes[curve.analysis] ?? null,
                },
            ];
        });
    });

    /** The instrument peaks of each curve, whatever the layer toggle says (the identifier reads them too). */
    const allInstrument = computed(() => {
        const loaded = table.value;
        if (!loaded || !active.value) return [];
        return sources.curves().map((curve) => {
            const { anode, kV } = excitationOf(curve);
            return instrumentPeaks(
                { x: curve.x, y: curve.rawY },
                anode,
                kV,
                loaded,
                fwhmMn.value,
            );
        });
    });
    const instrumentOfCurves = computed(() =>
        layers.value.instrument ? allInstrument.value : [],
    );

    function elementOf(symbol: string): XrfElement | undefined {
        return table.value?.elements[symbol];
    }

    /** The lines of `symbol` the window draws: inside its X range and excitable. */
    function drawnLines(symbol: string): LineRef[] {
        const element = elementOf(symbol);
        const range = windowRange.value;
        if (!element || !range) return [];
        return focusLines(element).filter(
            (line) =>
                line.energy >= range[0] &&
                line.energy <= range[1] &&
                excitable(
                    element.lines[line.name],
                    element.edges,
                    windowKv.value,
                ),
        );
    }

    function linesOf(symbol: string) {
        return drawnLines(symbol).map((line) => ({
            label: `${symbol} ${line.label}`,
            energy: line.energy,
            intensity: line.intensity,
        }));
    }

    const focusGroups = computed<FocusLines[]>(() => {
        const groups: FocusLines[] = pinned.value.map(({ symbol, slot }) => ({
            hue: slot - 1,
            lines: linesOf(symbol),
        }));
        const preview = previewed.value;
        if (preview) {
            groups.push({
                hue: (preview.slot ?? 1) - 1,
                preview: true,
                lines: linesOf(preview.symbol),
            });
        }
        return groups;
    });
    const lensGroups = computed<LensElementLines[]>(() =>
        lensSymbols.value.map((symbol) => ({ lines: linesOf(symbol) })),
    );

    /** The elements declared on the analyses of the visible curves, by symbol. */
    function declaredSymbols(curves: readonly LensCurve[]): Set<string> {
        return new Set(
            curves.flatMap((curve) => [
                ...(declaredOfCurve(curve)?.keys() ?? []),
            ]),
        );
    }

    const overlapInfo = computed(() => {
        const range = windowRange.value;
        const none = {
            bands: [] as OverlapBand[],
            notes: [] as StripOverlap[],
        };
        if (!active.value || !layers.value.overlaps || !table.value || !range) {
            return none;
        }
        const loaded = table.value;
        const curves = sources.curves();
        const fwhm = (energy: number) => fwhmAt(energy, fwhmMn.value);
        const kV = windowKv.value;
        const context = { fwhmAt: fwhm, range, kV };
        const hueOf = (symbol: string) => {
            const held = pinned.value.find((entry) => entry.symbol === symbol);
            return held ? held.slot - 1 : -1;
        };
        const subjects = drawnSymbols.value;
        const full = (symbol: string) =>
            drawnLines(symbol).map((line) => ({ symbol, line }));
        const principal = (symbol: string) => {
            const element = loaded.elements[symbol];
            const line = element ? principalLine(element, range, kV) : null;
            return line ? [{ symbol, line }] : [];
        };
        const pairs: [string, string, boolean][] = [];
        subjects.forEach((one, index) => {
            subjects
                .slice(index + 1)
                .forEach((other) => pairs.push([one, other, false]));
            for (const other of declaredSymbols(curves)) {
                if (!subjects.includes(other) && other in loaded.elements) {
                    pairs.push([one, other, true]);
                }
            }
        });
        const bands: OverlapBand[] = [];
        const notes: StripOverlap[] = [];
        for (const [one, other, againstDeclared] of pairs) {
            const found = overlaps(
                full(one),
                againstDeclared ? principal(other) : full(other),
                fwhm,
            );
            for (const overlap of found) {
                const hue = hueOf(one) >= 0 ? hueOf(one) : hueOf(other);
                bands.push({
                    from: overlap.centre - overlap.width / 2,
                    to: overlap.centre + overlap.width / 2,
                    hue,
                });
                if (notes.length >= MAX_OVERLAP_NOTES) continue;
                const apart = tellApart(
                    { symbol: one, element: loaded.elements[one] },
                    overlap.a.line,
                    { symbol: other, element: loaded.elements[other] },
                    overlap.b.line,
                    context,
                );
                notes.push({
                    a: lineRefOf(one, overlap.a.line),
                    b: lineRefOf(other, overlap.b.line),
                    apartA: apart.a ? lineRefOf(one, apart.a) : null,
                    apartB: apart.b ? lineRefOf(other, apart.b) : null,
                });
            }
        }
        return { bands, notes };
    });

    /** The declared ticks of a curve: each element's principal line inside the curve's range. */
    function declaredTicks(curve: LensCurve): LensPanel["declared"] {
        const loaded = table.value;
        const entries = declaredOfCurve(curve);
        if (!loaded || !entries || !curve.extent) return [];
        const range: [number, number] = [curve.extent.min, curve.extent.max];
        const { kV } = excitationOf(curve);
        return [...entries].flatMap(([symbol, entry]) => {
            const element = loaded.elements[symbol];
            const line = element ? principalLine(element, range, kV) : null;
            return line
                ? [
                      {
                          symbol,
                          energy: line.energy,
                          rank: entry.rank ?? UNRANKED,
                      },
                  ]
                : [];
        });
    }

    const model = computed<LensModel>(() => {
        const empty: LensModel = {
            panels: [],
            focus: [],
            elements: [],
            overlaps: [],
        };
        if (!active.value || !table.value) return empty;
        const curves = sources.curves();
        const hidden = sources.hidden();
        const groups: { suffix: string; indices: number[] }[] =
            sources.layout() === "multiples"
                ? sources.slots().map((slot, panel) => ({
                      suffix: panel === 0 ? "" : String(panel + 1),
                      indices: curves.flatMap((curve, index) =>
                          curve.slot === slot ? [index] : [],
                      ),
                  }))
                : [{ suffix: "", indices: curves.map((_, index) => index) }];
        const panels = groups.flatMap(({ suffix, indices }) => {
            const extent = union(
                indices.flatMap((index) => {
                    const held = curves[index].extent;
                    return held ? [held] : [];
                }),
            );
            if (!extent) return [];
            const visible = indices.filter((index) => !hidden[index]);
            const declaredBySymbol = new Map<
                string,
                LensPanel["declared"][number]
            >();
            if (layers.value.declared) {
                for (const index of visible) {
                    for (const tick of declaredTicks(curves[index])) {
                        const held = declaredBySymbol.get(tick.symbol);
                        if (!held || tick.rank < held.rank) {
                            declaredBySymbol.set(tick.symbol, tick);
                        }
                    }
                }
            }
            const ticks: PanelModel["ticks"] = [];
            const bands: PanelModel["bands"] = [];
            for (const index of visible) {
                for (const peak of instrumentOfCurves.value[index] ?? []) {
                    const curveOrder = curves[index].order;
                    if (peak.kind === "compton") {
                        if (
                            !bands.some(
                                (held) =>
                                    Math.abs(held.from - peak.from) <
                                        TICK_MERGE_KEV &&
                                    Math.abs(held.to - peak.to) <
                                        TICK_MERGE_KEV,
                            )
                        ) {
                            bands.push({
                                curveOrder,
                                label: labels().compton,
                                from: peak.from,
                                to: peak.to,
                            });
                        }
                        continue;
                    }
                    if (
                        ticks.some(
                            (held) =>
                                Math.abs(held.energy - peak.energy) <
                                TICK_MERGE_KEV,
                        )
                    ) {
                        continue;
                    }
                    ticks.push({
                        curveOrder,
                        label: instrumentLabel(peak, labels()),
                        energy: peak.energy,
                    });
                }
            }
            return [
                {
                    suffix,
                    extent,
                    declared: [...declaredBySymbol.values()],
                    ticks,
                    bands,
                },
            ];
        });
        return {
            panels,
            focus: focusGroups.value,
            elements: lensGroups.value,
            overlaps: overlapInfo.value.bands,
        };
    });

    /** The shapes of the lens in `theme`; empty when the window is not XRF or the table is not loaded. */
    function shapes(theme: PlotTheme): LensShape[] {
        const current = model.value;
        if (current.panels.length === 0) return [];
        const colourOf = (order: number) => theme.series[itemHue(order)];
        const panels: LensPanel[] = current.panels.map((panel) => ({
            suffix: panel.suffix,
            extent: panel.extent,
            declared: panel.declared,
            instrument: panel.ticks.map(
                (tick): InstrumentTick => ({
                    label: tick.label,
                    energy: tick.energy,
                    colour: colourOf(tick.curveOrder),
                }),
            ),
            bands: panel.bands.map(
                (band): EnergyBand => ({
                    label: band.label,
                    from: band.from,
                    to: band.to,
                    colour: colourOf(band.curveOrder),
                }),
            ),
        }));
        return lensShapes({
            panels,
            focus: current.focus,
            elements: current.elements,
            overlaps: current.overlaps,
            theme: {
                ink: theme.ink,
                inkMuted: theme.inkMuted,
                focus: theme.focus,
                fontMono: theme.fontMono,
            },
        });
    }

    /** What the strip lists: one entry per pinned, previewed or lens element. */
    const stripElements = computed<StripElement[]>(() => {
        const loaded = table.value;
        if (!active.value || !loaded) return [];
        const curves = sources.curves();
        const entryOf = (
            symbol: string,
            kind: ElementKind,
            slot: number | null,
        ): StripElement => {
            const known = symbol in loaded.elements;
            return {
                symbol,
                kind,
                slot,
                known,
                lines: known
                    ? drawnLines(symbol).map((line) => ({
                          label: line.label,
                          energy: line.energy,
                      }))
                    : [],
                declared: declaredPartsOf(symbol, curves),
            };
        };
        return [
            ...pinned.value.map(({ symbol, slot }) =>
                entryOf(symbol, "pinned", slot),
            ),
            ...(previewed.value
                ? [
                      entryOf(
                          previewed.value.symbol,
                          "preview",
                          previewed.value.slot,
                      ),
                  ]
                : []),
            ...lensSymbols.value.map((symbol) => entryOf(symbol, "lens", null)),
        ];
    });

    function declaredPartsOf(
        symbol: string,
        curves: readonly LensCurve[],
    ): DeclaredParts | null {
        const data = synthesis?.value;
        if (!data || !layers.value.declared) return null;
        const holders = curves.filter((curve) =>
            declaredOfCurve(curve)?.has(symbol),
        );
        if (holders.length === 0) return null;
        const merged = mergeDeclared(
            holders.map((curve) => declaredOfCurve(curve)),
        ).get(symbol);
        if (!merged) return null;
        merged.materials.sort(
            (a, b) =>
                (a.level?.rank ?? Infinity) - (b.level?.rank ?? Infinity) ||
                a.id.localeCompare(b.id),
        );
        return declaredParts(merged, holders[0].analysis, data, store.basket);
    }

    /** What each slot's analyses declare, best level first. */
    const declaredSlots = computed<StripDeclaredSlot[]>(() => {
        if (!active.value || !layers.value.declared) return [];
        const curves = sources.curves();
        return sources.slots().flatMap((slot) => {
            const maps = curves
                .filter((curve) => curve.slot === slot)
                .map((curve) => declaredOfCurve(curve));
            const merged: Map<string, DeclaredElement> = mergeDeclared(maps);
            if (merged.size === 0) return [];
            return [
                {
                    slot,
                    items: [...merged]
                        .sort(
                            ([, a], [, b]) =>
                                (a.rank ?? Infinity) - (b.rank ?? Infinity),
                        )
                        .map(([symbol, entry]) => ({
                            symbol,
                            level:
                                [...entry.materials].sort(
                                    (a, b) =>
                                        (a.level?.rank ?? Infinity) -
                                        (b.level?.rank ?? Infinity),
                                )[0]?.level?.label ?? null,
                        })),
                },
            ];
        });
    });

    /**
     * The energy a click at `energy` means on curve `index`: the local
     * maximum of its raw counts within half a FWHM, whatever the treatment.
     */
    function snapEnergy(index: number, energy: number): number {
        const curve = sources.curves()[index];
        if (!curve || curve.x.length === 0) return energy;
        const at = snapToPeak(
            curve.x,
            curve.rawY,
            energy,
            fwhmAt(energy, fwhmMn.value) / 2,
        );
        return curve.x[at] ?? energy;
    }

    /** The spacing of curve `index`'s channels (keV), to the micro-keV; 0 when it has none. */
    function channelOf(index: number): number {
        const curve = sources.curves()[index];
        return curve ? Math.round(channelWidth(curve.x) * 1e6) / 1e6 : 0;
    }

    /** The match tolerance (keV) around `energy`. */
    function toleranceAt(energy: number): number {
        return tolerance(energy, fwhmMn.value);
    }

    /** The tube voltage (kV) of curve `index`; null when unknown. */
    function kVOf(index: number): number | null {
        const curve = sources.curves()[index];
        return curve ? excitationOf(curve).kV : null;
    }

    /** What a peak at `energy` on curve `index` may be; empty until the line table is loaded. */
    function candidatesAt(index: number, energy: number): Candidate[] {
        const loaded = table.value;
        const curve = sources.curves()[index];
        if (!loaded || !curve) return [];
        return candidates(energy, {
            table: loaded,
            x: curve.x,
            y: curve.rawY,
            kV: excitationOf(curve).kV,
            fwhmMn: fwhmMn.value,
            declaredForCurve: declaredOfCurve(curve) ?? new Map(),
            declaredInSelection: mergeDeclared(declared.value.values()),
            lensElements: new Set(settings.value.elements),
            instrumentPeaks: allInstrument.value[index] ?? [],
        });
    }

    /** The parts of « declared major in Vermilion (A30) » for an element's entry, read from curve `index`'s analysis. */
    function declaredPartsAt(
        index: number,
        entry: DeclaredElement,
    ): DeclaredParts | null {
        const data = synthesis?.value;
        const curve = sources.curves()[index];
        if (!data || !curve) return null;
        const materials = [...entry.materials].sort(
            (a, b) =>
                (a.level?.rank ?? Infinity) - (b.level?.rank ?? Infinity) ||
                a.id.localeCompare(b.id),
        );
        return declaredParts(
            { ...entry, materials },
            curve.analysis,
            data,
            store.basket,
        );
    }

    /** Whether `symbol` is an `el:` node of the Selection's graph, so the focus can hold it. */
    function pinnable(symbol: string): boolean {
        return linked?.graph?.value?.nodes?.has(elementNode(symbol)) ?? false;
    }

    function isPinned(symbol: string): boolean {
        return pinned.value.some((held) => held.symbol === symbol);
    }

    /** Pins or unpins `el:<symbol>` in the focus; nothing when the graph has no such node. */
    function togglePin(symbol: string): void {
        if (pinnable(symbol)) linked?.toggle(elementNode(symbol));
    }

    watch(
        active,
        (on) => {
            if (!on || table.value) return;
            loadLineTable()
                .then((loaded) => {
                    if (!disposed) table.value = loaded;
                })
                .catch((error: unknown) => {
                    console.error(
                        "The XRF line table could not be loaded",
                        error,
                    );
                });
        },
        { immediate: true },
    );
    onScopeDispose(() => {
        disposed = true;
    });

    return {
        active,
        table,
        layers,
        settings,
        symbols,
        anodeRows,
        drawnSymbols,
        model,
        shapes,
        overlapNotes: computed(() => overlapInfo.value.notes),
        stripElements,
        declaredSlots,
        setDetector,
        setAnode,
        addElement,
        removeElement,
        toggleElement,
        snapEnergy,
        channelOf,
        toleranceAt,
        kVOf,
        candidatesAt,
        declaredPartsAt,
        pinnable,
        isPinned,
        togglePin,
    };
}

export type XrfLens = ReturnType<typeof useXrfLens>;

function instrumentLabel(peak: InstrumentPeak, labels: LensLabels): string {
    switch (peak.kind) {
        case "rayleigh":
            return `${peak.source ?? ""} ${peak.line ?? ""}`.trim();
        case "duane-hunt":
            return labels.voltage(peak.energy);
        case "escape":
            return labels.escape;
        default:
            return labels.sum;
    }
}
