import { describe, it, expect } from "vitest";
import initHomepageSearch from "./homepage-search";

const BASE = "/en/search-term";

describe("initHomepageSearch", () => {
    function boot() {
        document.body.innerHTML = `
            <form id="ms-search-form" action="${BASE}" method="get">
                <input id="ms-search-input" name="q">
            </form>
            <button type="button" class="ms-search-chip" data-term="XRF">XRF</button>`;
        return initHomepageSearch(document);
    }

    it("leaves the form submit to the browser", () => {
        boot();
        const event = new Event("submit", { cancelable: true });
        document.getElementById("ms-search-form").dispatchEvent(event);
        expect(event.defaultPrevented).toBe(false);
    });

    it("fills and focuses the input with a chip's term, without navigating", () => {
        boot();
        const input = document.getElementById("ms-search-input");
        input.value = "old";
        const click = new MouseEvent("click", {
            cancelable: true,
            bubbles: true,
        });
        document.querySelector(".ms-search-chip").dispatchEvent(click);
        expect(input.value).toBe("XRF");
        expect(document.activeElement).toBe(input);
        expect(click.defaultPrevented).toBe(false);
    });

    it("stops listening after destroy", () => {
        const destroy = boot();
        destroy();
        document.querySelector(".ms-search-chip").click();
        expect(document.getElementById("ms-search-input").value).toBe("");
    });

    it("does nothing without its form", () => {
        document.body.innerHTML = "";
        expect(initHomepageSearch(document)).toBeTypeOf("function");
    });

    it("leaves chip links alone", () => {
        document.body.innerHTML = `
            <form id="ms-search-form" action="${BASE}"><input id="ms-search-input" name="q"></form>
            <a class="ms-search-chip" href="/en/discover?grain=analyses&technique=x">Technique A</a>`;
        initHomepageSearch(document);
        document.addEventListener("click", (event) => event.preventDefault(), {
            once: true,
        });
        document
            .querySelector(".ms-search-chip")
            .dispatchEvent(
                new MouseEvent("click", { cancelable: true, bubbles: true }),
            );
        expect(document.getElementById("ms-search-input").value).toBe("");
    });
});
