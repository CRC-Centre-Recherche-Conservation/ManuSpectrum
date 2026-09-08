/**
 * Knockout binding: `thumbFallback`
 *
 * Hardens remote thumbnail <img> tags against third-party image hosts that
 * refuse cross-origin embedding — the concrete case being Biblissima result
 * thumbnails hosted on gallica.bnf.fr, which sits behind Cloudflare:
 *
 *   - the browser cannot embed the image cross-origin because the response
 *     carries a restrictive `Cross-Origin-Resource-Policy` (the console
 *     "…blocked due to its Cross-Origin-Resource-Policy header (or lack
 *     thereof)" warning), and/or
 *   - Cloudflare bot-challenges / 403s the hotlinked request outright.
 *
 * We can't fix the remote policy, and a server-side proxy is a dead end for
 * Gallica specifically (it 403s our server too, being Gallica's own bot
 * policy — verified). So this binding does the two things that *do* help on
 * the client:
 *
 *   1. sends the request without a `Referer` (`referrerpolicy=no-referrer`),
 *      which some hosts require to serve a hotlinked image at all, and
 *   2. on load failure, swaps the broken-image glyph for a self-contained
 *      SVG placeholder that matches the `fa-file-text-o` fallback used
 *      elsewhere in the Biblissima cards.
 *
 * Usage (alongside the existing `attr` src binding):
 *
 *   <img data-bind="attr: {src: thumbnail, alt: label}, thumbFallback: true"
 *        loading="lazy">
 */
import ko from "knockout";

// Document glyph on a light panel, mirroring the `fa-file-text-o` used by the
// `ko ifnot: thumbnail` branches. Inline data URI: no network, so it can never
// itself error and re-trigger the handler.
const PLACEHOLDER_SVG =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' +
    '<rect width="100" height="100" fill="#f0f0f2"/>' +
    '<g fill="none" stroke="#b8b8c0" stroke-width="4" ' +
    'stroke-linejoin="round" stroke-linecap="round">' +
    '<rect x="28" y="20" width="44" height="60" rx="3"/>' +
    '<path d="M36 42h28M36 54h28M36 66h18"/>' +
    "</g></svg>";
const PLACEHOLDER = "data:image/svg+xml," + encodeURIComponent(PLACEHOLDER_SVG);

ko.bindingHandlers.thumbFallback = {
    init: function (element) {
        element.setAttribute("referrerpolicy", "no-referrer");

        element.addEventListener("error", function () {
            // Already showing the placeholder — nothing to do (and guards
            // against any theoretical re-entry).
            if (element.getAttribute("src") === PLACEHOLDER) {
                return;
            }
            element.classList.add("bbma-thumb-failed");
            element.setAttribute("src", PLACEHOLDER);
        });
    },
};
