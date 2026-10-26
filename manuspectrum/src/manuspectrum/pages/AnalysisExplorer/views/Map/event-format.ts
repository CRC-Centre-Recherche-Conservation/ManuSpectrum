import type { EventDate } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

type Interpolate = (
    msgid: string,
    values: Record<string, string | number>,
    disableHtmlEscaping?: boolean,
) => string;

/** « 1301–1400 », « c. 1300 », « c. 1290–1310 » or « undated ». */
export function formatEventDate(
    date: EventDate,
    $gettext: (msgid: string) => string,
    interpolate: Interpolate,
): string {
    const start = date.start ?? date.end;
    const end = date.end ?? date.start;
    if (start === null || end === null) return $gettext("undated");
    const years =
        start === end
            ? String(start)
            : interpolate($gettext("%{start}–%{end}"), { start, end }, true);
    return date.approximate
        ? interpolate($gettext("c. %{year}"), { year: years }, true)
        : years;
}
