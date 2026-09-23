/**
 * Homepage search box and suggestion chips.
 *
 * Both navigate to the Arches search page with one string term filter. The
 * base URL is the form's `action`, rendered by `{% url 'search_home' %}`, so
 * it carries the page language.
 */

/**
 * @param {string} base search page URL
 * @param {string} query raw user input; trimmed, blank means no filter
 * @returns {string}
 */
export function buildSearchUrl(base, query) {
    const term = (query || "").trim();
    if (!term) {
        return base;
    }
    const termFilter = JSON.stringify([{
        inverted: false,
        type: "string",
        context: "",
        context_label: "",
        id: term,
        text: term,
        value: term,
    }]);
    return `${base}?paging-filter=1&term-filter=${encodeURIComponent(termFilter)}`;
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
    const input = form.querySelector("#ms-search-input");
    const chips = Array.from(root.querySelectorAll(".ms-search-chip"));
    const go = (query) => navigate(buildSearchUrl(form.getAttribute("action"), query));
    const onSubmit = (event) => {
        event.preventDefault();
        go(input ? input.value : "");
    };
    const onChip = (event) => go(event.currentTarget.dataset.term);
    form.addEventListener("submit", onSubmit);
    chips.forEach((chip) => chip.addEventListener("click", onChip));
    return () => {
        form.removeEventListener("submit", onSubmit);
        chips.forEach((chip) => chip.removeEventListener("click", onChip));
    };
}
