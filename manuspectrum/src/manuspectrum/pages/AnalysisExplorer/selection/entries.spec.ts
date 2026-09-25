import { describe, expect, it } from "vitest";

import {
    characterizationKey,
    entryKeyOf,
    fileKey,
    layerKey,
} from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import {
    analysisPayload,
    fileEntry,
    imagingEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

describe("Selection keys", () => {
    it("writes the three key shapes", () => {
        expect(fileKey(uuid(1), uuid(2))).toBe(`af:${uuid(1)}:${uuid(2)}`);
        expect(layerKey(uuid(1), 3)).toBe(`im:${uuid(1)}:3`);
        expect(characterizationKey(uuid(1))).toBe(`ch:${uuid(1)}:-`);
    });

    it("enters an analysis by its readable spectrum first", () => {
        const payload = analysisPayload({
            files: [
                fileEntry({ id: uuid(9), role: "raw", dataKind: "file" }),
                fileEntry({ id: uuid(8) }),
            ],
        });
        expect(entryKeyOf(payload)).toBe(`af:${payload.id}:${uuid(8)}`);
    });

    it("falls back to its first imaging layer, then to a micro-image", () => {
        expect(entryKeyOf(analysisPayload({ files: [imagingEntry()] }))).toBe(
            `im:${uuid(101)}:0`,
        );
        const micro = fileEntry({
            id: uuid(7),
            role: "other",
            dataKind: "micro-imaging",
            previewUrl: null,
        });
        expect(entryKeyOf(analysisPayload({ files: [micro] }))).toBe(
            `af:${uuid(101)}:${uuid(7)}`,
        );
    });

    it("has no entry for an analysis with nothing to show", () => {
        const raw = fileEntry({
            role: "raw",
            dataKind: "file",
            previewUrl: null,
        });
        expect(entryKeyOf(analysisPayload({ files: [raw] }))).toBeNull();
    });
});
