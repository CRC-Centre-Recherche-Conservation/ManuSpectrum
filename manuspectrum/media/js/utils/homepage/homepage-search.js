import listen, { stopAll } from "./listen";

/**
 * Homepage suggestion chips.
 *
 * The search form submits natively to the project route in its `action`
 * (`{% url 'search-term' %}`), which redirects to the Arches search page with
 * one string term filter: that redirect is the only place the filter is
 * shaped. A chip button navigates to the same route with its term. A submit
 * button carrying `formaction` (« Discover the data ») submits natively to its
 * own page with `q`; chips that are links are left to the browser.
 */

/**
 * @param {string} base the search-term route (the form's `action`)
 * @param {string} query raw user input; blank means no term
 * @returns {string}
 */
export function buildSearchUrl(base, query) {
    const term = (query || "").trim();
    return term ? `${base}?q=${encodeURIComponent(term)}` : base;
}

/**
 * @param {ParentNode} [root=document]
 * @param {{ navigate?: (url: string) => void }} [options]
 * @returns {() => void} removes the listeners
 */
export default function initHomepageSearch(root = document, { navigate = (url) => window.location.assign(url) } = {}) {
    const form = root.querySelector("#ms-search-form");
    if (!form) {
        return () => {};
    }
    const chips = Array.from(root.querySelectorAll("button.ms-search-chip[data-term]"));
    const onChip = (event) => navigate(buildSearchUrl(form.getAttribute("action"), event.currentTarget.dataset.term));
    const stops = chips.map((chip) => listen(chip, "click", onChip));
    return () => stopAll(stops);
}
