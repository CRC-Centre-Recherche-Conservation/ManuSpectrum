import { describe, expect, it } from "vitest";

import { webglAvailable } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/webgl.ts";

function canvasWith(
    getContext: (kind: string) => unknown,
): () => HTMLCanvasElement {
    return () => ({ getContext }) as unknown as HTMLCanvasElement;
}

describe("webglAvailable", () => {
    it("is false when getContext throws", () => {
        expect(
            webglAvailable(
                canvasWith(() => {
                    throw new Error("blocked");
                }),
            ),
        ).toBe(false);
    });

    it("is false when every context is refused", () => {
        expect(webglAvailable(canvasWith(() => null))).toBe(false);
    });

    it("is true for a webgl2 context", () => {
        expect(
            webglAvailable(
                canvasWith((kind) => (kind === "webgl2" ? {} : null)),
            ),
        ).toBe(true);
    });

    it("falls back on webgl 1", () => {
        expect(
            webglAvailable(
                canvasWith((kind) => (kind === "webgl" ? {} : null)),
            ),
        ).toBe(true);
    });
});
