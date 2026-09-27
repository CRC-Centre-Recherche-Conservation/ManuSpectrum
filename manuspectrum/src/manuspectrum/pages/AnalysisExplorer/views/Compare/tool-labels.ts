import type { OfferedTool } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";

type Gettext = (msgid: string) => string;

/** The title of each tool, in « + Tool » and on its window; literal `$gettext` calls for extraction. */
export function toolTitles($gettext: Gettext): Record<OfferedTool, string> {
    return {
        coverage: $gettext("Coverage matrix"),
        "colour-material": $gettext("Colours × materials"),
        periodic: $gettext("Periodic table"),
        folio: $gettext("Folio image"),
    };
}
