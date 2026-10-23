import { describe, expect, it, vi } from "vitest";

import {
    folioLayerOf,
    registerExternalViewer,
    viewerFor,
    warmViewer,
} from "@/manuspectrum/pages/AnalysisExplorer/viewers/registry.ts";
import { loadPlotly } from "@/manuspectrum/pages/AnalysisExplorer/xy/plotly.ts";

vi.mock("@/manuspectrum/pages/AnalysisExplorer/xy/plotly.ts", () => ({
    loadPlotly: vi.fn(async () => ({})),
}));

describe("viewer registry", () => {
    it("draws spectra as points and imaging as frames", () => {
        expect(viewerFor("xy").folio).toBe("point");
        expect(viewerFor("chemical-imaging").folio).toBe("frame");
        expect(viewerFor("micro-imaging").folio).toBe("frame");
        expect(viewerFor("file").folio).toBe("point");
    });

    it("puts frames under the imaging zones toggle and points under the point analyses toggle", () => {
        expect(folioLayerOf("xy")).toBe("points");
        expect(folioLayerOf("file")).toBe("points");
        expect(folioLayerOf("chemical-imaging")).toBe("zones");
        expect(folioLayerOf("micro-imaging")).toBe("zones");
    });

    it("treats a kind without a registered renderer as a plain file", async () => {
        const entry = viewerFor("rti");
        expect(entry.kind).toBe("file");
        expect(entry.external).toBeNull();
    });

    it("mounts an external renderer registered for its kind, until it is unregistered", () => {
        const mount = vi.fn(() => ({ destroy: vi.fn() }));
        const unregister = registerExternalViewer("rti", mount, "frame");
        expect(viewerFor("rti")).toMatchObject({
            kind: "rti",
            folio: "frame",
            external: mount,
        });
        unregister();
        expect(viewerFor("rti").kind).toBe("file");
    });

    it("loads each built-in preview lazily", async () => {
        const component = await viewerFor("file").preview();
        expect(component).toBeTruthy();
    });

    it("starts loading Plotly with the spectrum preview, and nothing more for the other kinds", () => {
        warmViewer("file");
        expect(loadPlotly).not.toHaveBeenCalled();
        warmViewer("xy");
        expect(loadPlotly).toHaveBeenCalledTimes(1);
    });
});
