import { describe, it, expect, vi } from "vitest";

const calls = [];
let navShouldThrow = false;
vi.mock("utils/ms-nav", () => ({
    default: () => {
        if (navShouldThrow) {
            throw new Error("nav boom");
        }
        calls.push("nav");
    },
}));
vi.mock("utils/reveal-on-scroll", () => ({ default: () => calls.push("reveal") }));
vi.mock("../utils/homepage/homepage-search", () => ({ default: () => calls.push("search") }));
vi.mock("../utils/homepage/showcase-carousel", () => ({
    default: () => {
        throw new Error("boom");
    },
}));
vi.mock("../utils/homepage/xrf-compare", () => ({ default: () => calls.push("xrf") }));
vi.mock("../utils/homepage/analysis-viewer", () => ({ default: () => calls.push("analysis") }));
vi.mock("../utils/homepage/spectral-logo", () => ({ default: () => calls.push("logo") }));

describe("homepage entry", () => {
    it("starts every block even when one throws", async () => {
        const error = vi.spyOn(console, "error").mockImplementation(() => {});
        await import("./index");
        expect(calls).toEqual(["nav", "reveal", "search", "xrf", "analysis", "logo"]);
        expect(error).toHaveBeenCalledTimes(1);
    });

    it("starts the reveal and the blocks even when the nav throws", async () => {
        navShouldThrow = true;
        calls.length = 0;
        vi.resetModules();
        const error = vi.spyOn(console, "error").mockImplementation(() => {});
        await import("./index");
        expect(calls).toEqual(["reveal", "search", "xrf", "analysis", "logo"]);
        expect(error).toHaveBeenCalledTimes(2);
    });
});
