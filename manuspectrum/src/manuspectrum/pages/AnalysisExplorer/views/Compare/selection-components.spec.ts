import { describe, expect, it } from "vitest";

import {
    BASKET,
    BY_KEY,
    BY_KEY_WITH_COMPONENT,
    COMPONENT,
    K1,
    SYNTHESIS,
    SYNTHESIS_WITH_COMPONENT,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    label,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { selectionComponents } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/selection-components.ts";

describe("selectionComponents", () => {
    it("is empty for a Selection observing no component", () => {
        expect(selectionComponents(BASKET, BY_KEY, SYNTHESIS)).toEqual([]);
    });

    it("counts the analyses and identified materials observing each component, with its folios", () => {
        expect(
            selectionComponents(
                BASKET,
                BY_KEY_WITH_COMPONENT,
                SYNTHESIS_WITH_COMPONENT,
            ),
        ).toEqual([
            {
                id: K1,
                name: COMPONENT.name,
                folios: ["f. 12r", "f. 12v"],
                analyses: 1,
                materials: 1,
            },
        ]);
    });

    it("reads the items alone while the synthesis is not there", () => {
        expect(
            selectionComponents(BASKET, BY_KEY_WITH_COMPONENT, null),
        ).toEqual([
            {
                id: K1,
                name: COMPONENT.name,
                folios: [],
                analyses: 1,
                materials: 0,
            },
        ]);
    });

    it("orders the components of the coverage rows first, the others by name", () => {
        const border = {
            id: uuid(952),
            model: "component",
            name: label("Border"),
        };
        const alpha = {
            id: uuid(953),
            model: "component",
            name: label("Alpha"),
        };
        const synthesis = {
            ...SYNTHESIS_WITH_COMPONENT,
            coverage: SYNTHESIS_WITH_COMPONENT.coverage.map((row, index) =>
                index === 1
                    ? {
                          ...row,
                          components: [
                              { component: border, counts: row.counts },
                          ],
                      }
                    : row,
            ),
            materials: SYNTHESIS_WITH_COMPONENT.materials.map(
                (material, index) =>
                    index === 1
                        ? {
                              ...material,
                              summary: {
                                  ...material.summary,
                                  objects: [alpha],
                              },
                          }
                        : material,
            ),
        };
        expect(
            selectionComponents(BASKET, BY_KEY_WITH_COMPONENT, synthesis).map(
                (component) => component.name.value,
            ),
        ).toEqual(["Initial T", "Border", "Alpha"]);
    });

    it("orders by name without regard to case or accents, then by id", () => {
        const component = (n: number, name: string) => ({
            id: uuid(n),
            model: "component",
            name: label(name),
        });
        const synthesis = {
            ...SYNTHESIS,
            coverage: [],
            materials: SYNTHESIS.materials.map((material, index) => ({
                ...material,
                summary: {
                    ...material.summary,
                    objects: [
                        [
                            component(956, "border"),
                            component(954, "Border"),
                            component(955, "Écu"),
                        ][index],
                    ],
                },
            })),
        };
        expect(
            selectionComponents(BASKET, BY_KEY, synthesis, "fr").map(
                (entry) => [entry.name.value, entry.id],
            ),
        ).toEqual([
            ["Border", uuid(954)],
            ["border", uuid(956)],
            ["Écu", uuid(955)],
        ]);
    });
});
