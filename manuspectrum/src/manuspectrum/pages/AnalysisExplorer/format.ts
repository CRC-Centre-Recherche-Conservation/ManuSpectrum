import type {
    DateRange,
    ProductionDates,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const KILO = 1000;
const ONE_DIGIT_BELOW = 10;
const WEB_SCHEMES = new Set(["http:", "https:"]);
const DOI_PREFIX = "10.";
const DOI_RESOLVER = "https://doi.org/";

/** A file size in kB or MB, in the page language; empty when unknown. */
export function formatSize(bytes: number | null, lang: string): string {
    if (bytes === null) return "";
    const [value, unit] =
        bytes >= KILO * KILO
            ? [bytes / (KILO * KILO), "megabyte"]
            : [bytes / KILO, "kilobyte"];
    return new Intl.NumberFormat(lang, {
        style: "unit",
        unit,
        unitDisplay: "short",
        maximumFractionDigits: value < ONE_DIGIT_BELOW ? 1 : 0,
    }).format(value);
}

/** A date or a start – end range as the server gives it (ISO dates, possibly year or year-month only). */
export function formatDateRange(range: DateRange): string {
    if (!range.start && !range.end) return "";
    if (!range.end || range.end === range.start)
        return range.start ?? range.end ?? "";
    return `${range.start ?? "…"} – ${range.end}`;
}

const CENTURY_YEARS = 100;
const HALF_YEARS = 50;
const QUARTER_YEARS = 25;
const YEAR = /^(\d{1,4})/;
const ROMAN: [number, string][] = [
    [1000, "M"],
    [900, "CM"],
    [500, "D"],
    [400, "CD"],
    [100, "C"],
    [90, "XC"],
    [50, "L"],
    [40, "XL"],
    [10, "X"],
    [9, "IX"],
    [5, "V"],
    [4, "IV"],
    [1, "I"],
];

type Translate = (msgid: string) => string;
type Interpolate = (
    msgid: string,
    context: Record<string, string | number>,
    disableHtmlEscaping?: boolean,
) => string;

/** A positive integer in Roman numerals. */
export function toRoman(n: number): string {
    let rest = Math.floor(n);
    let out = "";
    for (const [value, symbol] of ROMAN) {
        while (rest >= value) {
            out += symbol;
            rest -= value;
        }
    }
    return out;
}

function yearOf(bound: string | null): number | null {
    const found = bound ? YEAR.exec(bound) : null;
    return found ? Number(found[1]) : null;
}

/** « XVe » in French, « 15th » elsewhere. */
function ordinal(n: number, lang: string): string {
    if (lang.startsWith("fr")) return `${toRoman(n)}${n === 1 ? "er" : "e"}`;
    const suffixes: Record<string, string> = {
        one: "st",
        two: "nd",
        few: "rd",
    };
    const suffix =
        suffixes[new Intl.PluralRules("en", { type: "ordinal" }).select(n)] ??
        "th";
    return `${n}${suffix}`;
}

/**
 * A production date read on the years of its bounds (month and day ignored):
 * a year, a century, two centuries, a half or a quarter of a century, a plain
 * range or one open bound. « c. / vers » marks an approximate year or range;
 * centuries, halves and quarters already say they are imprecise.
 */
export function formatProductionDate(
    dates: ProductionDates,
    $gettext: Translate,
    interpolate: Interpolate,
    lang = "en",
): string {
    const start = yearOf(dates.start);
    const end = yearOf(dates.end);
    const say = (text: string, context: Record<string, string | number>) =>
        interpolate(text, context, true);
    if (start === null && end === null) return "";
    if (start === null || end === null) {
        const year = start ?? end ?? 0;
        if (start !== null) {
            return say(
                dates.approximate
                    ? $gettext("from c. %{year}")
                    : $gettext("from %{year}"),
                { year },
            );
        }
        return say(
            dates.approximate
                ? $gettext("until c. %{year}")
                : $gettext("until %{year}"),
            { year },
        );
    }
    if (start === end) {
        return say(
            dates.approximate ? $gettext("c. %{year}") : $gettext("%{year}"),
            { year: start },
        );
    }
    const offset = (start - 1) % CENTURY_YEARS;
    const century = Math.floor((start - 1) / CENTURY_YEARS) + 1;
    const length = end - start + 1;
    if (start > 0 && length === CENTURY_YEARS && offset === 0) {
        return say($gettext("%{century} century"), {
            century: ordinal(century, lang),
        });
    }
    if (start > 0 && length === 2 * CENTURY_YEARS && offset === 0) {
        return say($gettext("%{from} – %{to} c."), {
            from: ordinal(century, lang),
            to: ordinal(century + 1, lang),
        });
    }
    if (start > 0 && length === HALF_YEARS && offset % HALF_YEARS === 0) {
        const context = { century: ordinal(century, lang) };
        return say(
            offset === 0
                ? $gettext("1st half of the %{century} c.")
                : $gettext("2nd half of the %{century} c."),
            context,
        );
    }
    if (start > 0 && length === QUARTER_YEARS && offset % QUARTER_YEARS === 0) {
        const context = { century: ordinal(century, lang) };
        const quarters = [
            $gettext("1st quarter of the %{century} c."),
            $gettext("2nd quarter of the %{century} c."),
            $gettext("3rd quarter of the %{century} c."),
            $gettext("4th quarter of the %{century} c."),
        ];
        return say(quarters[offset / QUARTER_YEARS], context);
    }
    return say(
        dates.approximate
            ? $gettext("c. %{start} – %{end}")
            : $gettext("%{start} – %{end}"),
        { start, end },
    );
}

/**
 * An address safe to put in `href`: an absolute http or https URL as given, a
 * bare DOI (`10.xxxx/…`) as its doi.org address, a path of this site (one
 * leading `/`, read on no other host) as given; null for anything else (other
 * schemes, protocol-relative or relative paths, empty values).
 */
export function safeHref(url: string | null | undefined): string | null {
    const value = url?.trim() ?? "";
    if (value === "") return null;
    if (value.startsWith("/")) return sitePath(value);
    const candidate = value.startsWith(DOI_PREFIX)
        ? `${DOI_RESOLVER}${value}`
        : value;
    try {
        const parsed = new URL(candidate);
        return WEB_SCHEMES.has(parsed.protocol) ? parsed.href : null;
    } catch {
        return null;
    }
}

/** A path that stays on the page's host once the browser reads it; null when it would leave it (`//host`, `/\host`). */
function sitePath(value: string): string | null {
    try {
        const parsed = new URL(value, window.location.origin);
        return parsed.origin === window.location.origin ? value : null;
    } catch {
        return null;
    }
}

/** `text` without accents, in lower case: the form two labels are compared in. */
export function foldText(text: string): string {
    return text
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase();
}

/** Whether two texts read the same once folded (`foldText`) and their whitespace collapsed. */
export function sameText(a: string, b: string): boolean {
    const fold = (text: string): string =>
        foldText(text).replace(/\s+/g, " ").trim();
    return fold(a) === fold(b);
}
