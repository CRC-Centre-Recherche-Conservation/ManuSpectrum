import { describe, expect, it } from "vitest";

import {
    contentStateLink,
    miradorLink,
} from "@/manuspectrum/pages/AnalysisExplorer/share/content-state.ts";

const MANIFEST = "http://testserver/iiif/v3/explorer-manifest?ids=an:x:-";
const STATE =
    "http://testserver/iiif/v3/content-state/00000000-0000-4000-8000-000000000101/00000000-0000-4000-8000-000000000901";
const MIRADOR = "https://viewer.example/mirador/";

function params(link: string | null): URLSearchParams {
    expect(link).not.toBeNull();
    return new URL(link as string).searchParams;
}

describe("miradorLink", () => {
    it("opens a manifest by its URL", () => {
        const link = miradorLink(MIRADOR, { manifest: MANIFEST });
        expect(link?.startsWith(MIRADOR)).toBe(true);
        expect(params(link).get("manifest")).toBe(MANIFEST);
        expect(params(link).has("iiif-content")).toBe(false);
    });

    it("opens a content state by its URL as iiif-content", () => {
        const link = miradorLink(MIRADOR, { contentState: STATE });
        expect(params(link).get("iiif-content")).toBe(STATE);
        expect(params(link).has("manifest")).toBe(false);
    });

    it("keeps the viewer's own query", () => {
        const link = miradorLink("https://viewer.example/?theme=dark", {
            manifest: MANIFEST,
        });
        expect(params(link).get("theme")).toBe("dark");
        expect(params(link).get("manifest")).toBe(MANIFEST);
    });

    it("gives nothing without a viewer or for another scheme", () => {
        expect(miradorLink("", { manifest: MANIFEST })).toBeNull();
        expect(
            miradorLink("javascript:alert(1)", { manifest: MANIFEST }),
        ).toBeNull();
        expect(miradorLink("/relative", { manifest: MANIFEST })).toBeNull();
    });
});

describe("contentStateLink", () => {
    it("links the viewer with the state url unencoded", () => {
        const link = contentStateLink(MIRADOR, STATE);
        expect(link.startsWith(MIRADOR)).toBe(true);
        expect(params(link).get("iiif-content")).toBe(STATE);
        expect(link).toBe(miradorLink(MIRADOR, { contentState: STATE }));
    });

    it("copies the state url without a viewer", () => {
        expect(contentStateLink("", STATE)).toBe(STATE);
    });

    it("refuses a viewer that is not http(s)", () => {
        expect(contentStateLink("javascript:alert(1)", STATE)).toBe(STATE);
        expect(contentStateLink("/relative", STATE)).toBe(STATE);
    });
});
