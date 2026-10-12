import {
    createExpression,
    validateStyleMin,
} from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it, vi } from "vitest";

import {
    OHM_TILES,
    WATER_LAYER,
    baseStyle,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/base-style.ts";
import { FALLBACK_COLOURS } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-colours.ts";
import { ringRadius } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/place-symbols.ts";
import {
    HATCH_IMAGE,
    OHM_SOURCE,
    PIP_OFFSETS,
    PLACES_SOURCE,
    RING_DASHED_IMAGE,
    TERRITORIES_SOURCE,
    bordersFilter,
    bordersLayer,
    dashedRingImage,
    hatchImage,
    pipImage,
    placeLayers,
    stageImages,
    territoryLayers,
    territoryOpacity,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/stage-layers.ts";

import type { LayerSpecification, StyleSpecification } from "maplibre-gl";

const PLACES = placeLayers(FALLBACK_COLOURS);
const TERRITORIES = territoryLayers(FALLBACK_COLOURS);

function layer(
    layers: LayerSpecification[],
    id: string,
): LayerSpecification & {
    layout?: Record<string, unknown>;
    paint?: Record<string, unknown>;
    filter?: unknown;
} {
    const found = layers.find((candidate) => candidate.id === id);
    if (!found) throw new Error(`no layer ${id}`);
    return found as ReturnType<typeof layer>;
}

/** The value of a data expression for one feature, through MapLibre's own evaluator. */
function evaluate(
    value: unknown,
    properties: Record<string, unknown>,
    state: Record<string, unknown> = {},
    zoom = 6,
): unknown {
    const compiled = createExpression(value);
    if (compiled.result !== "success") {
        throw new Error(JSON.stringify(compiled.value));
    }
    return compiled.value.evaluate(
        { zoom },
        { type: "Point", properties, geometry: [] } as never,
        state,
    );
}

describe("the full stage style", () => {
    it("validates against the MapLibre style spec", () => {
        const base = baseStyle(FALLBACK_COLOURS);
        const style: StyleSpecification = {
            ...base,
            sources: {
                ...base.sources,
                [PLACES_SOURCE]: {
                    type: "geojson",
                    data: { type: "FeatureCollection", features: [] },
                    promoteId: "id",
                },
                [TERRITORIES_SOURCE]: {
                    type: "geojson",
                    data: { type: "FeatureCollection", features: [] },
                },
                [OHM_SOURCE]: { type: "vector", tiles: [OHM_TILES] },
            },
            layers: [
                ...TERRITORIES,
                ...base.layers,
                bordersLayer(1350, FALLBACK_COLOURS, true),
                ...PLACES,
            ],
        };
        expect(validateStyleMin(style)).toEqual([]);
    });
});

describe("placeLayers", () => {
    it("stacks rings, points, pips, then labels", () => {
        const ids = PLACES.map((candidate) => candidate.id);
        expect(ids.slice(0, 3)).toEqual([
            "place-rings",
            "place-rings-dashed",
            "place-points",
        ]);
        expect(ids.slice(-2)).toEqual(["place-labels", "place-badges"]);
        expect(ids.filter((id) => id.startsWith("pip-"))).toHaveLength(8);
    });

    it("reads the slot states in paint opacity only, never in layout", () => {
        for (let slot = 1; slot <= 4; slot++) {
            for (const kind of ["firm", "pale"]) {
                const pip = layer(PLACES, `pip-${slot}-${kind}`);
                expect(JSON.stringify(pip.paint?.["icon-opacity"])).toContain(
                    `["feature-state","t${slot}"]`,
                );
                expect(JSON.stringify(pip.layout)).not.toContain(
                    "feature-state",
                );
                expect(pip.layout?.["icon-image"]).toBe(
                    pipImage(slot, kind === "pale"),
                );
            }
        }
        for (const candidate of PLACES) {
            expect(
                JSON.stringify(
                    (candidate as { layout?: unknown }).layout ?? {},
                ),
            ).not.toContain("feature-state");
        }
    });

    it("shows the firm pip for level 1, the hollow one for level 2, none for 0", () => {
        const firm = layer(PLACES, "pip-2-firm").paint?.["icon-opacity"];
        const pale = layer(PLACES, "pip-2-pale").paint?.["icon-opacity"];
        expect(evaluate(firm, {}, { t2: 1 })).toBe(1);
        expect(evaluate(pale, {}, { t2: 1 })).toBe(0);
        expect(evaluate(firm, {}, { t2: 2 })).toBe(0);
        expect(evaluate(pale, {}, { t2: 2 })).toBe(1);
        expect(evaluate(firm, {}, { t2: 0 })).toBe(0);
    });

    it("sets each pip on the outer edge of its ring, 4 px out", () => {
        const offset = layer(PLACES, "pip-1-firm").layout?.["icon-offset"];
        const small = ringRadius(1);
        expect(evaluate(offset, { ring: small }, {}, 7)).toEqual(
            PIP_OFFSETS[0],
        );
        const large = ringRadius(25);
        const [x, y] = evaluate(offset, { ring: large }, {}, 7) as number[];
        expect(x).toBeCloseTo(0);
        expect(y).toBeCloseTo(-(large + 4));
        const third = layer(PLACES, "pip-3-firm").layout?.["icon-offset"];
        const [x3, y3] = evaluate(third, { ring: large }, {}, 7) as number[];
        expect(Math.hypot(x3, y3)).toBeCloseTo(large + 4, 2);
        expect(Math.atan2(y3, x3) * (180 / Math.PI)).toBeCloseTo(10, 1);
    });

    it("shrinks the pips at low zoom and keeps them on the ring's edge", () => {
        const pip = layer(PLACES, "pip-2-firm");
        const large = ringRadius(9);
        for (const [zoom, scale] of [
            [4, 0.75],
            [7, 1],
            [9, 1],
        ]) {
            const size = evaluate(pip.layout?.["icon-size"], {}, {}, zoom);
            expect(size).toBeCloseTo(scale);
            const [x, y] = evaluate(
                pip.layout?.["icon-offset"],
                { ring: large },
                {},
                zoom,
            ) as number[];
            expect(Math.hypot(x, y) * (size as number)).toBeCloseTo(
                large + 4,
                2,
            );
        }
    });

    it("gives the labels of the places with most documents the first place", () => {
        for (const id of ["place-labels", "place-badges"]) {
            const labels = layer(PLACES, id).layout ?? {};
            expect(labels["text-allow-overlap"]).toBe(false);
            expect(labels["text-variable-anchor"]).toEqual([
                "top",
                "bottom",
                "left",
                "right",
            ]);
            const key = labels["symbol-sort-key"];
            expect(evaluate(key, { documents: 9 })).toBeLessThan(
                evaluate(key, { documents: 2 }) as number,
            );
        }
    });

    it("rims the selected point in blue, not in a slot hue", () => {
        const stroke = layer(PLACES, "place-points").paint?.[
            "circle-stroke-color"
        ];
        expect(evaluate(stroke, { kind: "point" }, { selected: true })).toEqual(
            evaluate(FALLBACK_COLOURS.blue, {}),
        );
        expect(evaluate(stroke, { kind: "point" }, {})).toEqual(
            evaluate(FALLBACK_COLOURS.surface, {}),
        );
    });

    it("fades a dimmed place to the linked fade", () => {
        const opacity = layer(PLACES, "place-points").paint?.["circle-opacity"];
        expect(evaluate(opacity, {}, { dim: true })).toBe(0.35);
        expect(evaluate(opacity, {}, {})).toBe(1);
    });

    it("draws dashed places with the dashed ring image only", () => {
        const solid = layer(PLACES, "place-rings").filter;
        const dashed = layer(PLACES, "place-rings-dashed");
        expect(evaluate(solid, { dashed: true })).toBe(false);
        expect(evaluate(dashed.filter, { dashed: true })).toBe(true);
        expect(dashed.layout?.["icon-image"]).toBe(RING_DASHED_IMAGE);
    });
});

describe("territoryLayers", () => {
    it("holds a cell fill, a hatch fill on hatched cells and an edge line", () => {
        expect(TERRITORIES.map((candidate) => candidate.id)).toEqual([
            "territory-cells",
            "territory-hatch",
            "territory-edges",
        ]);
        const hatch = layer(TERRITORIES, "territory-hatch");
        expect(hatch.paint?.["fill-pattern"]).toBe(HATCH_IMAGE);
        expect(evaluate(hatch.filter, { layer: "cell", hatched: true })).toBe(
            true,
        );
        expect(evaluate(hatch.filter, { layer: "cell", hatched: false })).toBe(
            false,
        );
        expect(layer(TERRITORIES, "territory-edges").type).toBe("line");
    });

    it("paints a slot in its hue and a dominance frontier in surface", () => {
        const cells = layer(TERRITORIES, "territory-cells").paint?.[
            "fill-color"
        ];
        expect(evaluate(cells, { slot: 3 })).toEqual(
            evaluate(FALLBACK_COLOURS.focus[2], {}),
        );
        const edges = layer(TERRITORIES, "territory-edges").paint?.[
            "line-color"
        ];
        expect(evaluate(edges, { slot: 0 })).toEqual(
            evaluate(FALLBACK_COLOURS.surface, {}),
        );
    });

    it("isolates one slot by paint, fading the others' cells, hatch and edges", () => {
        const plain = territoryOpacity(null);
        expect(
            layer(TERRITORIES, "territory-cells").paint?.["fill-opacity"],
        ).toEqual(plain.cells);
        expect(
            layer(TERRITORIES, "territory-hatch").paint?.["fill-opacity"],
        ).toBe(0.55);
        expect(
            layer(TERRITORIES, "territory-edges").paint?.["line-opacity"],
        ).toBe(1);
        const only = territoryOpacity(4);
        expect(evaluate(only.cells, { slot: 4, alpha: 0.3 })).toBeCloseTo(0.3);
        expect(evaluate(only.cells, { slot: 1, alpha: 0.3 })).toBeCloseTo(0.06);
        expect(evaluate(only.edges, { slot: 4 })).toBe(1);
        expect(evaluate(only.edges, { slot: 0 })).toBeCloseTo(0.2);
        expect(evaluate(only.hatch, { slot: 2 })).toBeCloseTo(0.11);
    });

    it("leaves the sea layer to the base style", () => {
        expect(
            TERRITORIES.some((candidate) => candidate.id === WATER_LAYER),
        ).toBe(false);
    });
});

describe("bordersFilter", () => {
    it("keeps country borders alive in the middle of the year", () => {
        const filter = bordersFilter(1350);
        const text = JSON.stringify(filter);
        expect(text).toContain('["<=",["coalesce",["get","start_decdate"]');
        expect(text).toContain('[">=",["coalesce",["get","end_decdate"]');
        expect(text).toContain("1350.5");
        expect(
            evaluate(filter, {
                admin_level: 2,
                start_decdate: 1300,
                end_decdate: 1400,
            }),
        ).toBe(true);
        expect(evaluate(filter, { admin_level: 2, start_decdate: 1351 })).toBe(
            false,
        );
        expect(evaluate(filter, { admin_level: 1 })).toBe(true);
        expect(
            evaluate(filter, {
                admin_level: 4,
                start_decdate: 1300,
                end_decdate: 1400,
            }),
        ).toBe(false);
    });

    it("keeps only the admin level clause without a year", () => {
        const text = JSON.stringify(bordersFilter(null));
        expect(text).not.toContain("decdate");
        expect(text).toContain("admin_level");
        expect(evaluate(bordersFilter(null), { admin_level: 2 })).toBe(true);
    });

    it("draws the borders in the ring grey, dashed, hidden on request", () => {
        const borders = bordersLayer(null, FALLBACK_COLOURS, false) as {
            layout?: Record<string, unknown>;
            paint?: Record<string, unknown>;
        };
        expect(borders.paint?.["line-color"]).toBe(FALLBACK_COLOURS.ring);
        expect(borders.layout?.visibility).toBe("none");
    });
});

describe("the drawn images", () => {
    it("is transparent, at its size, without a 2D context", () => {
        const image = dashedRingImage("#000000", () => null);
        expect(image.width).toBe(64);
        expect(image.height).toBe(64);
        expect(image.data.every((value) => value === 0)).toBe(true);
    });

    it("draws the tie hatch in 1 CSS px paper lines", () => {
        const drawn: Record<string, unknown> = {};
        const context = new Proxy(
            {
                getImageData: vi.fn(() => ({
                    data: new Uint8ClampedArray(12 * 12 * 4),
                })),
            },
            {
                get: (target, key) =>
                    key in target
                        ? target[key as keyof typeof target]
                        : () => undefined,
                set: (_, key, value) => {
                    drawn[String(key)] = value;
                    return true;
                },
            },
        ) as unknown as CanvasRenderingContext2D;
        const image = hatchImage("#fbfaf6", () => context);
        expect(image.width).toBe(12);
        expect(drawn.lineWidth).toBe(2);
        expect(drawn.strokeStyle).toBe("#fbfaf6");
    });

    it("reads back what the context drew", () => {
        const drawn = new Uint8ClampedArray(28 * 28 * 4).fill(7);
        const context = new Proxy(
            {
                getImageData: vi.fn(() => ({ data: drawn })),
                setLineDash: vi.fn(),
            },
            {
                get: (target, key) =>
                    key in target
                        ? target[key as keyof typeof target]
                        : () => undefined,
                set: () => true,
            },
        ) as unknown as CanvasRenderingContext2D;
        const images = stageImages(FALLBACK_COLOURS, () => context);
        expect([...images.keys()]).toEqual([
            RING_DASHED_IMAGE,
            HATCH_IMAGE,
            "pip-firm-1",
            "pip-pale-1",
            "pip-firm-2",
            "pip-pale-2",
            "pip-firm-3",
            "pip-pale-3",
            "pip-firm-4",
            "pip-pale-4",
        ]);
        expect(images.get("pip-pale-3")?.width).toBe(28);
        expect(images.get("pip-pale-3")?.data[0]).toBe(7);
    });
});
