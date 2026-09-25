import type {
    Label,
    ValueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** Number of `--tech-n` colours in `_ms-chrome.scss`; further techniques are drawn in ink with their code. */
export const TECHNIQUE_COLOURS = 6;

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

/**
 * Technique families and their code, tried in this order on the label (English
 * or French, case and accents ignored): the first family that matches gives
 * the code, so a technique keeps its code in every document.
 */
const FAMILIES: readonly (readonly [RegExp, string])[] = [
    [
        /fluorescence x|x-?ray (micro)?fluorescence|\b(ma|µ|micro-?|p)?xrf\b/,
        "X",
    ],
    [/reflectance|fors\b/, "F"],
    [/raman/, "R"],
    [/mass|masse|maldi/, "MS"],
    [/imag|photograph/, "I"],
    [/infrared|infrarouge|\birtf\b|\bftir\b/, "IR"],
    [/microscop/, "M"],
    [/diffraction|\bxrd\b|\bdrx\b/, "D"],
];

/** The code of the family a technique label belongs to; null outside the families. */
export function familyCode(text: string): string | null {
    const plain = text
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase();
    return FAMILIES.find(([pattern]) => pattern.test(plain))?.[1] ?? null;
}

export function techniqueKey(technique: ValueRef | null): string {
    return technique?.uri ?? "";
}

function codeFor(text: string, taken: Set<string>): string {
    const letters = text.replace(/[^\p{L}\p{N}]/gu, "").toUpperCase() || "?";
    for (const candidate of [
        letters.slice(0, 1),
        letters.slice(0, 2),
        letters.slice(0, 3),
    ]) {
        if (candidate && !taken.has(candidate)) return candidate;
    }
    let suffix = 2;
    while (taken.has(`${letters.slice(0, 1)}${suffix}`)) suffix += 1;
    return `${letters.slice(0, 1)}${suffix}`;
}

/**
 * One style per technique of a document, ordered by label: a short code shown
 * in the marker and the legend, and the colour `--tech-1`…`--tech-6` in that
 * order. Colour follows the technique, never its rank among the markers shown.
 * A technique of a known family takes the family code; any other takes the
 * first letters of its label not already used in the document.
 */
export function techniqueStyles(
    techniques: readonly (ValueRef | null)[],
    fallback: Label,
): Map<string, TechniqueStyle> {
    const unique = new Map<string, Label>();
    for (const technique of techniques) {
        const key = techniqueKey(technique);
        if (!unique.has(key)) unique.set(key, technique?.label ?? fallback);
    }
    const sorted = [...unique.entries()].sort(([, a], [, b]) =>
        collator.compare(a.value, b.value),
    );
    const families = new Map(
        sorted.map(([key, text]) => [key, familyCode(text.value)]),
    );
    const taken = new Set<string>(
        [...families.values()].filter((code): code is string => code !== null),
    );
    const styles = new Map<string, TechniqueStyle>();
    sorted.forEach(([key, text], index) => {
        const code = families.get(key) ?? codeFor(text.value, taken);
        taken.add(code);
        styles.set(key, {
            key,
            label: text,
            code,
            colour: index < TECHNIQUE_COLOURS ? index + 1 : null,
        });
    });
    return styles;
}
