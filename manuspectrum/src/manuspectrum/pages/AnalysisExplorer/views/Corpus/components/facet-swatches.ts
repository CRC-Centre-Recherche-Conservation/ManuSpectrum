import { foldText } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";

/**
 * Display colours of common colour names, English and French, folded. They
 * only decorate the Colour facet: the data carries names, not a palette.
 */
const SWATCHES: Readonly<Record<string, string>> = {
    blue: "royalblue",
    bleu: "royalblue",
    azur: "royalblue",
    red: "firebrick",
    rouge: "firebrick",
    vermillon: "orangered",
    vermilion: "orangered",
    green: "forestgreen",
    vert: "forestgreen",
    gold: "goldenrod",
    golden: "goldenrod",
    or: "goldenrod",
    dore: "goldenrod",
    silver: "silver",
    argent: "silver",
    argente: "silver",
    white: "white",
    blanc: "white",
    black: "black",
    noir: "black",
    yellow: "gold",
    jaune: "gold",
    brown: "saddlebrown",
    brun: "saddlebrown",
    marron: "saddlebrown",
    beige: "beige",
    ochre: "peru",
    ocre: "peru",
    grey: "grey",
    gray: "grey",
    gris: "grey",
    purple: "purple",
    violet: "purple",
    pourpre: "purple",
    pink: "hotpink",
    rose: "hotpink",
    orange: "darkorange",
};

/** The display colour of the first colour word in `label`; null when it names none. */
export function colourSwatch(label: string): string | null {
    for (const word of foldText(label).split(/[^a-z]+/)) {
        if (Object.hasOwn(SWATCHES, word)) return SWATCHES[word];
    }
    return null;
}
