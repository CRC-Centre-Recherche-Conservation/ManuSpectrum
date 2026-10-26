/**
 * The words of `utils/xy-views.js` and `utils/xy-transforms.js`, which stay
 * free of any translation bundle: the Knockout side reads them from
 * `arches.translations`, the Explorer from these tables. Every call is a
 * literal `$gettext` so extraction sees each string.
 */
type Gettext = (msgid: string) => string;

/** The name of each view offered in the treatment menu, by view key. */
export function viewLabels($gettext: Gettext): Record<string, string> {
    return {
        base: $gettext("As measured"),
        "log-inverse-r": $gettext("Pseudo-absorbance log10(1/R)"),
        "kubelka-munk": $gettext("Kubelka-Munk"),
        "normalize-max": $gettext("Normalised to maximum"),
        "normalize-area": $gettext("Normalised to total (TIC)"),
        "derivative-1": $gettext("First derivative"),
        "derivative-2": $gettext("Second derivative"),
    };
}

/** A menu entry as it reads inside a sentence: its first letter in lower case. */
function inSentence(label: string): string {
    return label.charAt(0).toLocaleLowerCase() + label.slice(1);
}

/**
 * What a transform adds in brackets to the Y title, by transform key
 * (`deriveAxisLabel`). A normalisation is named with the words of its menu
 * entry (`viewLabels`), so the menu and the axis say the same thing.
 * `log10(1/R)` and `Kubelka-Munk` are a formula and a proper noun: the
 * module's own wording stands.
 */
export function annotationLabels($gettext: Gettext): Record<string, string> {
    const views = viewLabels($gettext);
    return {
        "normalize-max": inSentence(views["normalize-max"]),
        "normalize-area": inSentence(views["normalize-area"]),
        smooth: $gettext("smoothed"),
        derivative: $gettext("derivative"),
    };
}
