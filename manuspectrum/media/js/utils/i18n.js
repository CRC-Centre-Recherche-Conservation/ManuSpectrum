import arches from "arches";

// Translation helpers shared by the public pages. Each page's keys come from its
// `.arches-translations` partial (templates/includes/ms_i18n_*.htm, read by
// arches.js into arches.translations); the fallback is the English source
// string, so a missing key degrades to English, never to `undefined`.
export const t = (key, fallback) =>
    (arches.translations && arches.translations[key]) || fallback;

// Interpolating variant: `{name}` placeholders; an unknown one stays as written.
export const tv = (key, fallback, vars) =>
    String(t(key, fallback)).replace(/\{(\w+)\}/g, (m, name) =>
        Object.prototype.hasOwnProperty.call(vars || {}, name)
            ? String(vars[name])
            : m,
    );

// True when the page language uses its singular form for `n`: `one` in the
// CLDR plural rules, which French also gives to 0 ("0 notice publiée").
export const isSingular = (n) => {
    let rules;
    try {
        rules = new Intl.PluralRules(document.documentElement.lang || "en");
    } catch {
        rules = new Intl.PluralRules("en");
    }
    return rules.select(n) === "one";
};
