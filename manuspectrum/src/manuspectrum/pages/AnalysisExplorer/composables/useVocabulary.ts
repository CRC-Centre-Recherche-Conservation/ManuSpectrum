import { useGettext } from "vue3-gettext";

import type {
    DataKind,
    FacetKey,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { ExplorerView } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

/** Translated names of facets, data kinds and explorer views. */
export function useVocabulary(): {
    facetTitle: (key: FacetKey) => string;
    dataKindBadge: (kind: DataKind) => string;
    viewTitle: (view: ExplorerView) => string;
} {
    const { $gettext } = useGettext();

    function facetTitle(key: FacetKey): string {
        switch (key) {
            case "technique":
                return $gettext("Technique");
            case "part":
                return $gettext("Studied area");
            case "material":
                return $gettext("Identified material");
            case "colour":
                return $gettext("Colour");
            case "element":
                return $gettext("Element");
            case "layer":
                return $gettext("Layer");
            case "project":
                return $gettext("Project");
            case "operator":
                return $gettext("Operator");
            case "year":
                return $gettext("Year");
        }
    }

    function dataKindBadge(kind: DataKind): string {
        switch (kind) {
            case "xy":
                return $gettext("spectrum");
            case "chemical-imaging":
                return $gettext("map");
            case "micro-imaging":
                return $gettext("micro-image");
            case "file":
                return $gettext("file");
        }
    }

    function viewTitle(view: ExplorerView): string {
        switch (view) {
            case "corpus":
                return $gettext("Corpus");
            case "map":
                return $gettext("Map & timeline");
            case "compare":
                return $gettext("Compare");
        }
    }

    return { facetTitle, dataKindBadge, viewTitle };
}
