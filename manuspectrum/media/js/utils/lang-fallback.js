/**
 * Language fallback for the text and rich-text widgets.
 *
 * `msLangFallback(values, current, languages, prefix)` picks what a report or
 * display value shows for a multilingual field: the page language `current`
 * when its value is not blank, else the value of the first code of `languages`
 * (array of `{code}`) other than `current` that is not blank, else nothing.
 * `values` is the plain object `{<code>: {value}}` (`ko.toJS(displayValue())`).
 * It returns `{text, code, label}`: `code` is null when the page language
 * answers or nothing is filled; otherwise `label` is `prefix` followed by the
 * language name written in the page language (the code when the browser has no
 * name for it).
 *
 * Classic script (no import/export), loaded synchronously by
 * `templates/javascript.htm` before the Knockout bundle and exposed on
 * `globalThis` for the Knockout binding expressions of the widget templates.
 */
(function () {
    function msLangFallback(values, current, languages, prefix) {
        const nothing = { text: "", code: null, label: "" };
        if (!values || typeof values !== "object") {
            return nothing;
        }
        const read = function (code) {
            const entry = values[code];
            const value =
                entry && typeof entry === "object" ? entry.value : null;
            return value === null || value === undefined ? "" : String(value);
        };
        if (read(current).trim()) {
            return { text: read(current), code: null, label: "" };
        }
        const codes = (Array.isArray(languages) ? languages : []).map(
            function (language) {
                return language.code;
            },
        );
        for (let i = 0; i < codes.length; i++) {
            if (codes[i] !== current && read(codes[i]).trim()) {
                let name = codes[i];
                try {
                    name =
                        new Intl.DisplayNames([current], {
                            type: "language",
                        }).of(codes[i]) || name;
                } catch (_error) {
                    name = codes[i];
                }
                return {
                    text: read(codes[i]),
                    code: codes[i],
                    label: prefix + " " + name,
                };
            }
        }
        return nothing;
    }
    globalThis.msLangFallback = msLangFallback;
})();
