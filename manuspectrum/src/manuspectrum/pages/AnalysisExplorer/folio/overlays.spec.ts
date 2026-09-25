import L from "leaflet";
import { describe, expect, it } from "vitest";

import {
    curtainable,
    folioOverlays,
    layerImageUrl,
    overlayKey,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import {
    analysisPayload,
    annotation,
    imagingEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

describe("folio overlays", () => {
    it("asks the IIIF image at a bounded size", () => {
        expect(
            layerImageUrl({
                service: "https://iiif.example/pb/",
                url: null,
                width: 1,
                height: 1,
            }),
        ).toBe("https://iiif.example/pb/full/!2048,2048/0/default.jpg");
        expect(
            layerImageUrl({
                service: null,
                url: "https://x/pb.png",
                width: 1,
                height: 1,
            }),
        ).toBe("https://x/pb.png");
        expect(
            layerImageUrl({ service: null, url: null, width: 1, height: 1 }),
        ).toBeNull();
    });

    it("lays the layers switched on in the bounding box of the analysis zone", () => {
        const analysis = analysisPayload({ files: [imagingEntry()] });
        const zone = annotation(1, {
            dataKind: "chemical-imaging",
            shape: { type: "rect", x: 0, y: 0, w: 64, h: 32 },
        });
        const result = folioOverlays(
            analysis,
            {
                [overlayKey(uuid(101), 1)]: {
                    element: "Hg",
                    opacity: 0.6,
                    on: true,
                },
                [overlayKey(uuid(101), 0)]: {
                    element: "Pb",
                    opacity: 0.6,
                    on: false,
                },
            },
            [zone],
        );
        expect(result).toEqual([
            {
                key: `${uuid(101)}:1`,
                url: "https://iiif.example/image/hg/full/!2048,2048/0/default.jpg",
                bounds: [
                    [-1, 0],
                    [0, 2],
                ],
                opacity: 0.6,
                label: "Hg",
            },
        ]);
    });

    it("lays nothing when the analysis has only a point on this page", () => {
        const analysis = analysisPayload({ files: [imagingEntry()] });
        const result = folioOverlays(
            analysis,
            {
                [overlayKey(uuid(101), 0)]: {
                    element: "Pb",
                    opacity: 1,
                    on: true,
                },
            },
            [annotation(1)],
        );
        expect(result).toEqual([]);
    });

    it("lets leaflet-side-by-side clip an image overlay", () => {
        const overlay = curtainable(
            L.imageOverlay("x.png", [
                [0, 0],
                [1, 1],
            ]),
        );
        expect(
            typeof (overlay as unknown as { getContainer: () => unknown })
                .getContainer,
        ).toBe("function");
    });
});
