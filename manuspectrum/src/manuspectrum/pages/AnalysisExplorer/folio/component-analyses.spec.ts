import { describe, expect, it } from "vitest";

import {
    characterizationComponents,
    componentAnalyses,
    componentMaterials,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/component-analyses.ts";
import { documentView } from "@/manuspectrum/pages/AnalysisExplorer/folio/document-view.ts";
import { techniqueStyles } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import {
    characterization,
    documentComponent,
    documentMatch,
    documentPayload,
    label,
    technique,
    uuid,
    valueRef,
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

describe("componentMaterials and characterizationComponents", () => {
    const component = documentComponent(1);
    const other = documentComponent(2);
    const scale = [
        { ...valueRef("c:0", "Very reliable"), rank: 0 },
        { ...valueRef("c:2", "Plausible"), rank: 2 },
    ];

    function shown(
        summaries: ReturnType<typeof characterization>[],
        kept: string[] = summaries.map((entry) => entry.id),
    ) {
        const payload = documentPayload({
            techniques: { [XRF.uri]: XRF },
            analyses: [
                analysis(1, { component: component.id }),
                analysis(2, { component: other.id }),
            ],
            components: [component, other],
            characterizations: summaries,
        });
        return documentView(payload, {
            ...documentMatch(),
            kept: { analyses: null, characterizations: kept },
        });
    }

    const ref = (target: typeof component) => ({
        id: target.id,
        model: "component",
        name: target.name,
    });

    it("links a material that observes the component, or cites one of its analyses", () => {
        const observing = characterization(1, { objects: [ref(component)] });
        const citing = characterization(2, {
            evidence: [{ id: uuid(101), name: label("X01") }],
        });
        const elsewhere = characterization(3, {
            objects: [ref(other)],
            evidence: [{ id: uuid(102), name: label("X02") }],
        });
        const view = shown([observing, citing, elsewhere]);
        expect(
            componentMaterials(view, component.id).map((entry) => entry.id),
        ).toEqual([observing.id, citing.id]);
        expect(componentMaterials(view, uuid(799))).toEqual([]);
    });

    it("carries the name, the first colour swatch, the best certainty, the draft mark and the match", () => {
        const summary = characterization(1, {
            objects: [ref(component)],
            unpublished: true,
            colours: [
                { ...valueRef("c:none", "None"), swatch: null },
                { ...valueRef("c:red", "Red"), swatch: "#c00" },
            ],
            materials: [
                {
                    value: valueRef("m:a", "A"),
                    confidence: scale[1],
                    proportion: null,
                },
                {
                    value: valueRef("m:b", "B"),
                    confidence: scale[0],
                    proportion: null,
                },
            ],
        });
        const [entry] = componentMaterials(shown([summary], []), component.id);
        expect(entry).toEqual({
            id: summary.id,
            name: summary.name,
            swatch: "#c00",
            certainty: scale[0].label,
            unpublished: true,
            match: false,
        });
    });

    it("gives the components a material is linked to, by the same rule", () => {
        const summary = characterization(1, {
            objects: [ref(component)],
            evidence: [{ id: uuid(102), name: label("X02") }],
        });
        const view = shown([summary]);
        expect(
            characterizationComponents(view, summary).map((entry) => entry.id),
        ).toEqual([component.id, other.id]);
        expect(characterizationComponents(view, characterization(9))).toEqual(
            [],
        );
    });
});
