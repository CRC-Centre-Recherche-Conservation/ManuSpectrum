import { describe, expect, it } from "vitest";

import {
    cellNode,
    isRecordNode,
    kindOfNode,
    nodeId,
    pairNode,
    parseNodeId,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

describe("node ids", () => {
    it("reads back the kind and parts it was made of, URLs and separators included", () => {
        const canvas = "https://iiif.example/m|1/canvas:2";
        const id = cellNode(canvas, "http://example.org/xrf");
        expect(id.startsWith("cell:")).toBe(true);
        expect(parseNodeId(id)).toEqual({
            kind: "cell",
            parts: [canvas, "http://example.org/xrf"],
        });
    });

    it("writes a missing part empty and reads it back as null", () => {
        const id = pairNode(null, "http://example.org/chalk");
        expect(id).toBe("pair:|http%3A%2F%2Fexample.org%2Fchalk");
        expect(parseNodeId(id)?.parts).toEqual([
            null,
            "http://example.org/chalk",
        ]);
    });

    it("gives the same id for the same parts", () => {
        expect(nodeId("el", "Fe")).toBe("el:Fe");
        expect(nodeId("slot", 3)).toBe("slot:3");
        expect(nodeId("layer", "f", 0)).toBe(nodeId("layer", "f", "0"));
    });

    it("reads no kind it does not know, and no malformed id", () => {
        expect(parseNodeId("zz:1")).toBeNull();
        expect(parseNodeId("an")).toBeNull();
        expect(parseNodeId("an:%E0%A4%A")).toBeNull();
        expect(kindOfNode("zz:1")).toBeNull();
        expect(kindOfNode("an:1")).toBe("an");
    });

    it("counts analyses and identified materials as records, nothing else", () => {
        expect(isRecordNode("an:1")).toBe(true);
        expect(isRecordNode("ch:1")).toBe(true);
        expect(isRecordNode("file:1")).toBe(false);
        expect(isRecordNode("el:Fe")).toBe(false);
        expect(isRecordNode("nonsense")).toBe(false);
    });
});
