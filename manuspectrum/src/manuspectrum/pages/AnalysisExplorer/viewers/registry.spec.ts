import { describe, expect, it, vi } from "vitest";

import {
    registerExternalViewer,
    showsSpectrum,
    viewerFor,
} from "@/manuspectrum/pages/AnalysisExplorer/viewers/registry.ts";

describe("viewer registry", () => {
    it("draws spectra as points and imaging as frames", () => {
        expect(viewerFor("xy").folio).toBe("point");
        expect(viewerFor("chemical-imaging").folio).toBe("frame");
        expect(viewerFor("micro-imaging").folio).toBe("frame");
        expect(viewerFor("file").folio).toBe("point");
        expect(showsSpectrum("xy")).toBe(true);
        expect(showsSpectrum("chemical-imaging")).toBe(false);
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
});
