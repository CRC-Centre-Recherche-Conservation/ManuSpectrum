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

/**
 * What a transform adds in brackets to the Y title, by transform key
 * (`deriveAxisLabel`). `log10(1/R)` and `Kubelka-Munk` are a formula and a
 * proper noun: the module's own wording stands.
 */
export function annotationLabels($gettext: Gettext): Record<string, string> {
    return {
        "normalize-max": $gettext("normalised to max"),
        "normalize-area": $gettext("normalised to area"),
        smooth: $gettext("smoothed"),
        derivative: $gettext("derivative"),
    };
}
