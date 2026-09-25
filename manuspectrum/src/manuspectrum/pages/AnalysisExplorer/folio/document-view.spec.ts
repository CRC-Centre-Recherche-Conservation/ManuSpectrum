import { describe, expect, it } from "vitest";

import { documentView } from "@/manuspectrum/pages/AnalysisExplorer/folio/document-view.ts";
import {
    characterization,
    documentMatch,
    documentPayload,
    label,
    technique,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const XRF = technique("http://example.org/xrf", "XRF");
const C1 = "https://iiif.example/c1";
const C2 = "https://iiif.example/c2";

function payload() {
    return documentPayload({
        techniques: { [XRF.uri]: XRF },
        analyses: [
            {
                id: uuid(101),
                name: label("X01"),
                technique: XRF.uri,
                dataKind: "xy",
                unpublished: false,
                zones: [
                    { canvas: 0, shape: { type: "point", x: 1, y: 2 } },
                    { canvas: 1, shape: { type: "point", x: 3, y: 4 } },
                ],
            },
            {
                id: uuid(102),
                name: label("X02"),
                technique: null,
                dataKind: "file",
                unpublished: true,
                zones: [],
            },
        ],
        characterizations: [characterization(1), characterization(2)],
    });
}

describe("documentView", () => {
    it("spreads each analysis over its zones on the canvases their positions name", () => {
        const view = documentView(payload(), null);

        expect(
            view.annotations.map((entry) => [
                entry.key,
                entry.canvas,
                entry.technique,
            ]),
        ).toEqual([
            [`an:${uuid(101)}:0`, C1, XRF],
            [`an:${uuid(101)}:1`, C2, XRF],
        ]);
        expect(view.annotations[1].shape).toEqual({
            type: "point",
            x: 3,
            y: 4,
        });
    });

    it("lists an analysis without zones as unlocated", () => {
        const view = documentView(payload(), null);

        expect(view.unlocated).toEqual([
            {
                analysis: uuid(102),
                name: label("X02"),
                technique: null,
                dataKind: "file",
                unpublished: true,
                match: true,
            },
        ]);
    });

    it("keeps everything until a match arrives", () => {
        const view = documentView(payload(), null);

        expect(view.annotations.every((entry) => entry.match)).toBe(true);
        expect([...view.keptCharacterizations]).toEqual([uuid(501), uuid(502)]);
    });

    it("marks the analyses and identified materials the match keeps", () => {
        const view = documentView(
            payload(),
            documentMatch({
                kept: { analyses: [uuid(102)], characterizations: [uuid(502)] },
                total: 1,
            }),
        );

        expect(view.annotations.map((entry) => entry.match)).toEqual([
            false,
            false,
        ]);
        expect(view.unlocated[0].match).toBe(true);
        expect([...view.keptCharacterizations]).toEqual([uuid(502)]);
    });

    it("drops a zone whose canvas position is not in the payload", () => {
        const source = payload();
        source.analyses[0].zones[1].canvas = 9;

        const view = documentView(source, null);

        expect(view.annotations.map((entry) => entry.canvas)).toEqual([C1]);
    });
});
