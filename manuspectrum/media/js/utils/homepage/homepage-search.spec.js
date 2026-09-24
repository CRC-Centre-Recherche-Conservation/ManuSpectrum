import { describe, it, expect, vi } from "vitest";
import initHomepageSearch, { buildSearchUrl } from "./homepage-search";

const BASE = "/en/search";

function decodeFilter(url) {
    const params = new URLSearchParams(url.split("?")[1]);
    return { paging: params.get("paging-filter"), terms: JSON.parse(params.get("term-filter")) };
}

describe("buildSearchUrl", () => {
    it("builds one string term filter", () => {
        const { paging, terms } = decodeFilter(buildSearchUrl(BASE, "Vermilion"));
        expect(paging).toBe("1");
        expect(terms).toEqual([{
            inverted: false, type: "string", context: "", context_label: "",
            id: "Vermilion", text: "Vermilion", value: "Vermilion",
        }]);
    });

    it("keeps quotes, ampersands and accents intact", () => {
        const term = 'plomb & "étain"';
        const url = buildSearchUrl(BASE, `  ${term} `);
        expect(url.startsWith(`${BASE}?paging-filter=1&term-filter=`)).toBe(true);
        expect(decodeFilter(url).terms[0].value).toBe(term);
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

    it("intercepts the submit and navigates with the typed term", () => {
        const { navigate } = boot();
        document.getElementById("ms-search-input").value = "Raman";
        const event = new Event("submit", { cancelable: true });
        document.getElementById("ms-search-form").dispatchEvent(event);
        expect(event.defaultPrevented).toBe(true);
        expect(decodeFilter(navigate.mock.calls[0][0]).terms[0].value).toBe("Raman");
    });

    it("navigates with a chip's term", () => {
        const { navigate } = boot();
        document.querySelector(".ms-search-chip").click();
        expect(decodeFilter(navigate.mock.calls[0][0]).terms[0].value).toBe("XRF");
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

    it("lets a submitter with formaction go to its own page natively", () => {
        document.body.innerHTML = `
            <form id="ms-search-form" action="${BASE}" method="get">
                <input id="ms-search-input" name="q">
                <button type="submit" class="plain">Search</button>
                <button type="submit" class="discover" formaction="/en/discover">Discover</button>
            </form>`;
        const navigate = vi.fn();
        initHomepageSearch(document, { navigate });
        const form = document.getElementById("ms-search-form");
        const discover = new SubmitEvent("submit", { cancelable: true, submitter: form.querySelector(".discover") });
        form.dispatchEvent(discover);
        expect(discover.defaultPrevented).toBe(false);
        expect(navigate).not.toHaveBeenCalled();
        const plain = new SubmitEvent("submit", { cancelable: true, submitter: form.querySelector(".plain") });
        form.dispatchEvent(plain);
        expect(plain.defaultPrevented).toBe(true);
        expect(navigate).toHaveBeenCalledTimes(1);
    });

    it("leaves chip links alone", () => {
        document.body.innerHTML = `
            <form id="ms-search-form" action="${BASE}"><input id="ms-search-input" name="q"></form>
            <a class="ms-search-chip ms-technique-chip" href="/en/discover?grain=analyses&technique=http%3A%2F%2Fexample.org%2Ftechnique%2Fa">Technique A</a>`;
        const navigate = vi.fn();
        initHomepageSearch(document, { navigate });
        document.querySelector(".ms-search-chip").dispatchEvent(new MouseEvent("click", { cancelable: true }));
        expect(navigate).not.toHaveBeenCalled();
    });
});
