import type {
    CharacterizationSummary,
    Facet,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { Filters } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

type MaterialKey = "material" | "colour" | "element" | "layer";

const MATERIAL_KEYS: readonly MaterialKey[] = [
    "material",
    "colour",
    "element",
    "layer",
];

function valuesOf(
    summary: CharacterizationSummary,
    key: MaterialKey,
): string[] {
    switch (key) {
        case "material":
            return summary.materials.map((entry) => entry.value.uri);
        case "colour":
            return summary.colours.map((value) => value.uri);
        case "element":
            return summary.elements.flatMap((group) =>
                group.values.map((value) => value.uri),
            );
        case "layer":
            return summary.layers.map((value) => value.uri);
    }
}

export function hasMaterialFilters(filters: Filters): boolean {
    return MATERIAL_KEYS.some((key) => filters[key].length > 0);
}

/**
 * Whether the filters keep an identified material on the folio: OR inside a
 * facet, AND across the material, colour, element and layer facets. The other
 * facets describe analyses and leave identified materials lit. A selected
 * value that no facet of the search offers (`facets`) is ignored, as the
 * server's `row_filter` ignores a value no row carries.
 */
export function characterizationMatches(
    summary: CharacterizationSummary,
    filters: Filters,
    facets: readonly Facet[],
): boolean {
    return MATERIAL_KEYS.every((key) => {
        const offered = new Set(
            facets
                .find((facet) => facet.key === key)
                ?.values.map((value) => value.id) ?? [],
        );
        const wanted = filters[key].filter((value) => offered.has(value));
        return (
            wanted.length === 0 ||
            valuesOf(summary, key).some((value) => wanted.includes(value))
        );
    });
}
