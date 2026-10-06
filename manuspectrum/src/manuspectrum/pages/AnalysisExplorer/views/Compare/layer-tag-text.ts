import type { TagParts } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";

/** What a component gives `tagText` to translate and fill in (`useGettext`). */
export interface TagTranslate {
    $gettext: (msgid: string) => string;
    interpolate: (msgid: string, values: Record<string, string>) => string;
}

function bandText(
    band: NonNullable<TagParts["band"]>,
    unit: string | null,
): string {
    let range: string;
    if (band.value !== null) range = String(band.value);
    else if (band.lower !== null && band.upper !== null) {
        range = `${band.lower}–${band.upper}`;
    } else if (band.lower !== null) range = `≥ ${band.lower}`;
    else if (band.upper !== null) range = `≤ ${band.upper}`;
    else range = "";
    return unit && range ? `${range} ${unit}` : range;
}

/**
 * The short text of a tag, read off its parts: « Cu Lα » for declared
 * elements (and their line), « 650 nm » (or « ≥ 400 nm », « ≤ 700 nm » for a
 * bound alone) for a band, « PCA 3 » for a component with its method and
 * « Component 3 » without, else the content's label.
 */
export function tagText(
    parts: TagParts,
    { $gettext, interpolate }: TagTranslate,
): string {
    if (parts.symbols.length > 0) {
        const symbols = parts.symbols.join("+");
        return parts.line ? `${symbols} ${parts.line.value}` : symbols;
    }
    if (parts.band) {
        const band = bandText(parts.band, parts.unit);
        if (band) return band;
    }
    if (parts.index !== null) {
        return parts.method
            ? `${parts.method} ${parts.index}`
            : interpolate($gettext("Component %{index}"), {
                  index: String(parts.index),
              });
    }
    return parts.contentLabel.value;
}
