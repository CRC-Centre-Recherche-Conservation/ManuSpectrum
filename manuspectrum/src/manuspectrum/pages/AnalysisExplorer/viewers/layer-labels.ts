import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

type Gettext = (msgid: string) => string;

/** What a layer is called by its kind (D46): « Element », « Band », else « Layer »; literal `$gettext` calls for extraction. */
export function layerKindLabel(
    $gettext: Gettext,
    kind: FileLayer["kind"],
): string {
    switch (kind) {
        case "element":
            return $gettext("Element");
        case "band":
            return $gettext("Band");
        default:
            return $gettext("Layer");
    }
}
