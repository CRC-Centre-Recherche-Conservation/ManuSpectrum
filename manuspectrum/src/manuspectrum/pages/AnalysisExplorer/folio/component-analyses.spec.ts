import { describe, expect, it } from "vitest";

import { componentAnalyses } from "@/manuspectrum/pages/AnalysisExplorer/folio/component-analyses.ts";
import { documentView } from "@/manuspectrum/pages/AnalysisExplorer/folio/document-view.ts";
import { techniqueStyles } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import {
    documentMatch,
    documentPayload,
    label,
    technique,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { DocumentAnalysis } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const XRF = technique("http://example.org/xrf", "XRF");
const COMPONENT = uuid(701);

function analysis(
    n: number,
    overrides: Partial<DocumentAnalysis> = {},
): DocumentAnalysis {
    return {
        id: uuid(100 + n),
        name: label(`X0${n}`),
        technique: XRF.uri,
        dataKind: "xy",
        unpublished: false,
        component: COMPONENT,
        zones: [],
        ...overrides,
    };
}

function view(analyses: DocumentAnalysis[], kept: string[] | null = null) {
    const payload = documentPayload({
        techniques: { [XRF.uri]: XRF },
        analyses,
    });
    const match = documentMatch();
    return documentView(payload, {
        ...match,
        kept: { analyses: kept, characterizations: [] },
    });
}

describe("componentAnalyses", () => {
    it("lists once each analysis that observes the component, located or not, with its style", () => {
        const located = analysis(1, {
            zones: [
                {
                    canvas: 0,
                    shape: { type: "point", x: 1, y: 2 },
                    feature: uuid(901),
                },
                {
                    canvas: 1,
                    shape: { type: "point", x: 3, y: 4 },
                    feature: uuid(902),
                },
            ],
        });
        const elsewhere = analysis(3, { component: uuid(702) });
        const shown = view([
            located,
            analysis(2, { unpublished: true }),
            elsewhere,
        ]);
        const styles = techniqueStyles([XRF], label("Analysis"));
        const entries = componentAnalyses(shown, COMPONENT, styles);
        expect(entries.map((entry) => entry.id)).toEqual([
            uuid(101),
            uuid(102),
        ]);
        expect(entries[0].style?.code).toBe(XRF.code);
        expect(entries[1].unpublished).toBe(true);
        expect(entries[0].dataKind).toBe("xy");
    });

    it("marks the analyses the filters drop and finds none for an unknown component", () => {
        const shown = view([analysis(1), analysis(2)], [uuid(101)]);
        const styles = techniqueStyles([XRF], label("Analysis"));
        expect(
            componentAnalyses(shown, COMPONENT, styles).map(
                (entry) => entry.match,
            ),
        ).toEqual([true, false]);
        expect(componentAnalyses(shown, uuid(799), styles)).toEqual([]);
    });
});
