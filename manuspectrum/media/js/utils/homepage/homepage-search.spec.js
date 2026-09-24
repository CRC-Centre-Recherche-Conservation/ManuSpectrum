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
});
