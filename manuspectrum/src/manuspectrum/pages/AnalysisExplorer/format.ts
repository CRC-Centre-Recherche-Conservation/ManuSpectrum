import type { DateRange } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

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

/**
 * An address safe to put in `href`: an absolute http or https URL as given, a
 * bare DOI (`10.xxxx/…`) as its doi.org address; null for anything else
 * (other schemes, relative paths, empty values).
 */
export function safeHref(url: string | null | undefined): string | null {
    const value = url?.trim() ?? "";
    if (value === "") return null;
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
