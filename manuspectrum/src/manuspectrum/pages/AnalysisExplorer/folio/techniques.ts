import type {
    Label,
    Technique,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** Number of `--tech-n` colours in `_ms-chrome.scss`; the server gives no family a colour beyond it. */
export const TECHNIQUE_COLOURS = 10;

export interface TechniqueStyle {
    key: string;
    label: Label;
    code: string;
    colour: number | null;
}

const collator = new Intl.Collator(undefined, {
    sensitivity: "base",
    numeric: true,
});

export function techniqueKey(technique: Technique | null): string {
    return technique?.uri ?? "";
}

/**
 * One style per technique, keyed by its URI and ordered by label (the order
 * of the legend and the page list). Code and colour are the ones the server
 * gives the technique, the same in every language and document; an analysis
 * without a technique is drawn in ink under `fallback`.
 */
export function techniqueStyles(
    techniques: readonly (Technique | null)[],
    fallback: Label,
): Map<string, TechniqueStyle> {
    const unique = new Map<string, TechniqueStyle>();
    for (const technique of techniques) {
        const key = techniqueKey(technique);
        if (unique.has(key)) continue;
        unique.set(
            key,
            technique
                ? {
                      key,
                      label: technique.label,
                      code: technique.code,
                      colour: technique.colour,
                  }
                : { key, label: fallback, code: "?", colour: null },
        );
    }
    return new Map(
        [...unique.entries()].sort(([, a], [, b]) =>
            collator.compare(a.label.value, b.label.value),
        ),
    );
}

/** The class of a technique colour: `<prefix>--tech-n`, or `<prefix>--ink` without a colour. */
export function techniqueClass(prefix: string, colour: number | null): string {
    return colour ? `${prefix}--tech-${colour}` : `${prefix}--ink`;
}
