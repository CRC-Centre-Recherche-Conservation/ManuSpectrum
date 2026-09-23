import { describe, it, expect, vi } from "vitest";

const calls = [];
vi.mock("utils/ms-nav", () => ({ default: () => calls.push("nav") }));
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
});
