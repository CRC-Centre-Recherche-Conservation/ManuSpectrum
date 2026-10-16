import { describe, it, expect, vi } from "vitest";
import initHomepageSearch, { buildSearchUrl } from "./homepage-search";

const BASE = "/en/search-term";

describe("buildSearchUrl", () => {
    it("carries the trimmed term as q", () => {
        expect(buildSearchUrl(BASE, "Vermilion")).toBe(`${BASE}?q=Vermilion`);
    });

    it("keeps quotes, ampersands and accents intact", () => {
        const term = 'plomb & "étain"';
        const params = new URLSearchParams(buildSearchUrl(BASE, `  ${term} `).split("?")[1]);
        expect(params.get("q")).toBe(term);
    });

    it("returns the base for an empty or blank query", () => {
        expect(buildSearchUrl(BASE, "")).toBe(BASE);
        expect(buildSearchUrl(BASE, "   ")).toBe(BASE);
        expect(buildSearchUrl(BASE, undefined)).toBe(BASE);
    });
});

describe("initHomepageSearch", () => {
    function boot() {
        document.body.innerHTML = `
            <form id="ms-search-form" action="${BASE}" method="get">
                <input id="ms-search-input" name="q">
            </form>
            <button type="button" class="ms-search-chip" data-term="XRF">XRF</button>`;
        const navigate = vi.fn();
        const destroy = initHomepageSearch(document, { navigate });
        return { navigate, destroy };
    }

    it("leaves the form submit to the browser", () => {
        const { navigate } = boot();
        const event = new Event("submit", { cancelable: true });
        document.getElementById("ms-search-form").dispatchEvent(event);
        expect(event.defaultPrevented).toBe(false);
        expect(navigate).not.toHaveBeenCalled();
    });

    it("navigates to the form action with a chip's term", () => {
        const { navigate } = boot();
        document.querySelector(".ms-search-chip").click();
        expect(navigate).toHaveBeenCalledWith(`${BASE}?q=XRF`);
    });

    it("stops listening after destroy", () => {
        const { navigate, destroy } = boot();
        destroy();
        document.querySelector(".ms-search-chip").click();
        expect(navigate).not.toHaveBeenCalled();
    });

    it("does nothing without its form", () => {
        document.body.innerHTML = "";
        expect(initHomepageSearch(document)).toBeTypeOf("function");
    });

    it("leaves chip links alone", () => {
        document.body.innerHTML = `
            <form id="ms-search-form" action="${BASE}"><input id="ms-search-input" name="q"></form>
            <a class="ms-search-chip" href="/en/discover?grain=analyses&technique=x">Technique A</a>`;
        const navigate = vi.fn();
        initHomepageSearch(document, { navigate });
        document.querySelector(".ms-search-chip").dispatchEvent(new MouseEvent("click", { cancelable: true }));
        expect(navigate).not.toHaveBeenCalled();
    });
});
