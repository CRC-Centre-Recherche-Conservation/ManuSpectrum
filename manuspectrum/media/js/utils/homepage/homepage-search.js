import listen, { stopAll } from "./listen";

/**
 * Homepage suggestion chips.
 *
 * The search form has two submit buttons: the first goes to the project route
 * in its `action` (`{% url 'search-term' %}`, which redirects to the Arches
 * search page with one string term filter), the second carries `formaction`
 * and goes to the Data Lab. Both submit natively. A chip button only fills the
 * input with its term and focuses it, so the visitor picks the tool; chips
 * that are links are left to the browser.
 */

/**
 * @param {ParentNode} [root=document]
 * @returns {() => void} removes the listeners
 */
export default function initHomepageSearch(root = document) {
    const input = root.querySelector("#ms-search-input");
    if (!input) {
        return () => {};
    }
    const chips = Array.from(root.querySelectorAll("button.ms-search-chip[data-term]"));
    const onChip = (event) => {
        input.value = event.currentTarget.dataset.term;
        input.focus();
    };
    const stops = chips.map((chip) => listen(chip, "click", onChip));
    return () => stopAll(stops);
}
