import { useGettext } from "vue3-gettext";

import type {
    DataKind,
    FacetGroup,
    FacetKey,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    ColourLevel,
    ExplorerView,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

/** Translated names of facets, facet groups, colour levels, data kinds and explorer views. */
export function useVocabulary(): {
    facetTitle: (key: FacetKey) => string;
    filterTitle: (key: FacetKey) => string;
    groupTitle: (group: FacetGroup) => string;
    levelLabel: (level: ColourLevel) => string;
    levelOption: (level: ColourLevel) => string;
    levelHint: (level: ColourLevel) => string;
    dataKindBadge: (kind: DataKind) => string;
    viewTitle: (view: ExplorerView) => string;
} {
    const { $gettext } = useGettext();

    /** The title of a facet in the rail; both colour facets are « Colour » there, told apart by the toggle. */
    function facetTitle(key: FacetKey): string {
        switch (key) {
            case "partType":
                return $gettext("Type");
            case "partColour":
            case "colour":
                return $gettext("Colour");
            case "technique":
                return $gettext("Technique");
            case "part":
                return $gettext("Area");
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
                return $gettext("Year");
        }
    }

    /** The name of a facet outside the rail (active filters): a colour facet names its level. */
    function filterTitle(key: FacetKey): string {
        switch (key) {
            case "partColour":
                return $gettext("Colour (part)");
            case "colour":
                return $gettext("Colour (identified)");
            case "part":
                return $gettext("Studied area");
            case "material":
                return $gettext("Identified material");
            default:
                return facetTitle(key);
        }
    }

    function groupTitle(group: FacetGroup): string {
        switch (group) {
            case "part":
                return $gettext("Studied part");
            case "analysis":
                return $gettext("Analysis");
            case "characterization":
                return $gettext("Identified material");
        }
    }

    function levelLabel(level: ColourLevel): string {
        return level === "partColour"
            ? $gettext("Seen on the part")
            : $gettext("Identified by analysis");
    }

    /** The short name of a colour level on its toggle option; `levelHint` explains it. */
    function levelOption(level: ColourLevel): string {
        return level === "partColour" ? $gettext("Part") : $gettext("Analysis");
    }

    function levelHint(level: ColourLevel): string {
        return level === "partColour"
            ? $gettext(
                  "Colours described on the studied part, even without analysis",
              )
            : $gettext(
                  "Colour of the area where a material was identified from the analyses",
              );
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
        levelLabel,
        levelOption,
        levelHint,
        dataKindBadge,
        viewTitle,
    };
}
