import { describe, it, expect, vi } from "vitest";

describe("Arches modules on a page without javascript.htm", () => {
    it("arches.js loads with no .arches-* nodes", async () => {
        document.body.innerHTML = "";
        vi.resetModules();
        const arches = (await vi.importActual("arches")).default;
        expect(arches.urls).toBeUndefined();
        expect(arches.translations).toBeUndefined();
    });

    it("template-loader loads without arches.urls", async () => {
        document.body.innerHTML = "";
        vi.resetModules();
        await expect(vi.importActual("arches/arches/app/media/js/template-loader")).resolves.toBeDefined();
    });
});
