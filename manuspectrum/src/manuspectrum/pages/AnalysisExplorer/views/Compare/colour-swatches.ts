const INHA = "https://thesaurus.inha.fr/thesaurus/resource/ark:/54721/";

/**
 * The display colour of each concept of the colour list (« AGORHA - Color »,
 * INHA thesaurus), keyed by the concept's URI, the same in every language: a
 * CSS colour, or a gradient for the metallic ones.
 */
const SWATCHES: ReadonlyMap<string, string> = new Map(
    Object.entries({
        "d549884f-ed29-4a28-87c8-07311d9a14ad": "#2f55a4",
        "8fea5a73-2d20-4fcf-a1a5-84c886c25152": "#b8322a",
        "65911707-7503-4511-a7f8-50d7950e8178": "#d9772b",
        "23d3e025-d192-44a3-b402-8e7549cad396": "#e3b53b",
        "28b1b584-6607-49cf-acff-67e7f16dae68": "#3f7d4e",
        "0e604a6e-3c95-4608-a7b8-5f99fcd506e5": "#6d4a8f",
        "0bfbc388-6da7-4209-995d-33c72c08fb9f": "#e3a1a8",
        "c3c194f1-5237-4e1c-ad3d-38cb2351b8eb": "#7a4e2d",
        "b4028a43-aafc-4d54-bdf7-8c901c693d14": "#26232b",
        "2259f089-935b-46ec-af76-cdb5156ee311": "#f5f0e4",
        "aa134bc0-36d8-4156-a1f6-8f3241f70a93": "#8f8c86",
        "71aa53c3-0322-4111-bf82-98fa14f62393": "#d9c8a4",
        "163d790d-859f-4a9d-92ae-2f759a1d8b6b":
            "linear-gradient(135deg, #e9ebee, #a9adb4 55%, #dfe2e6)",
        "c1e1850f-9eb1-48f4-b8b8-6154a3a1623c":
            "linear-gradient(135deg, #f3dc8a, #b8891f 55%, #ecd07a)",
        "3219663b-bd8b-4e14-8dc8-02eaf6e1f793":
            "linear-gradient(135deg, #e0a27a, #a8562c 55%, #d98d62)",
    }).map(([id, swatch]) => [`${INHA}${id}`, swatch]),
);

/** The swatch of the colour concept `uri`; null for a concept the list does not hold. */
export function swatchOf(uri: string): string | null {
    return SWATCHES.get(uri) ?? null;
}
