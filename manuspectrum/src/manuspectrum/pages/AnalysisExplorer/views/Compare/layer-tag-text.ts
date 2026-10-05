import type { TagParts } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";

function bandText(
    band: NonNullable<TagParts["band"]>,
    unit: string | null,
): string {
    const range =
        band.value !== null
            ? String(band.value)
            : `${band.lower ?? ""}–${band.upper ?? ""}`;
    return unit ? `${range} ${unit}` : range;
}

/**
 * The short text of a tag, read off its parts: « Cu Lα » for declared
 * elements (and their line), « 650 nm » for a band, « <content> 3 » for a
 * component, else the content's label.
 */
export function tagText(parts: TagParts): string {
    if (parts.symbols.length > 0) {
        const symbols = parts.symbols.join("+");
        return parts.line ? `${symbols} ${parts.line.value}` : symbols;
    }
    if (parts.band) return bandText(parts.band, parts.unit);
    if (parts.index !== null) {
        return `${parts.contentLabel.value} ${parts.index}`;
    }
    return parts.contentLabel.value;
}
