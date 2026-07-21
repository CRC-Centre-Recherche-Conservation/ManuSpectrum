import arches from "arches";

// Translation helpers shared by the public pages (was copy-pasted in
// graph-explorer.js, contact.js and conceptual-model.js — as `tr`/`trv` in the
// latter). Keys live in templates/javascript.htm (→ arches.translations);
// the fallback is the English source string, so a missing key degrades to
// English, never to `undefined`.
export const t = (key, fallback) =>
    (arches.translations && arches.translations[key]) || fallback;

// Interpolating variant: `{name}` placeholders, same convention as the
// biblissima-batch-* keys already in javascript.htm.
export const tv = (key, fallback, vars) =>
    String(t(key, fallback)).replace(/\{(\w+)\}/g, (m, name) =>
        Object.prototype.hasOwnProperty.call(vars || {}, name)
            ? String(vars[name])
            : m,
    );
