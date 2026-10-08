import { useGettext } from "vue3-gettext";

import type {
    DataKind,
    FacetGroup,
    FacetKey,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { ExplorerView } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

/** Translated names of facets, facet groups, colour scopes, data kinds and explorer views. */
export function useVocabulary(): {
    facetTitle: (key: FacetKey) => string;
    filterTitle: (key: FacetKey) => string;
    groupTitle: (group: FacetGroup) => string;
    periodTitle: () => string;
    dataKindBadge: (kind: DataKind) => string;
    viewTitle: (view: ExplorerView) => string;
} {
    const { $gettext } = useGettext();

    /** The title of a facet in the rail. */
    function facetTitle(key: FacetKey): string {
        switch (key) {
            case "place":
                return $gettext("Place of production");
            case "partType":
                return $gettext("Type");
            case "colour":
                return $gettext("Colour");
            case "technique":
                return $gettext("Technique");
            case "part":
                return $gettext("Component");
            case "material":
                return $gettext("Material");
            case "element":
                return $gettext("Element");
            case "layer":
                return $gettext("Layer");
            case "project":
                return $gettext("Project");
            case "operator":
                return $gettext("Operator");
            case "year":
                return $gettext("Analysis year");
        }
    }

    /** The name of a facet outside the rail (active filters). */
    function filterTitle(key: FacetKey): string {
        switch (key) {
            case "part":
                return $gettext("Studied component");
            case "material":
                return $gettext("Identified material");
            default:
                return facetTitle(key);
        }
    }

    /** The title of the production-date facet, which has no `FacetKey`. */
    function periodTitle(): string {
        return $gettext("Date of production");
    }

    function groupTitle(group: FacetGroup): string {
        switch (group) {
            case "document":
                return $gettext("Document");
            case "part":
                return $gettext("Studied component");
            case "analysis":
                return $gettext("Analysis");
            case "characterization":
                return $gettext("Identified material");
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

    return {
        facetTitle,
        filterTitle,
        groupTitle,
        periodTitle,
        dataKindBadge,
        viewTitle,
    };
}
