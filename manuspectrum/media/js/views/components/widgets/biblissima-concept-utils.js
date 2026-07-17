/**
 * Pure helpers for the biblissima-concept widget — kept import-free so
 * vitest can exercise them without the webpack-alias stubs (the mocked
 * WidgetViewModel/bindings make the widget viewmodel itself untestable).
 */

const ENTITY_URI_BASE = 'https://data.biblissima.fr/entity/';
const PORTAL_BASE = 'https://portail.biblissima.fr/';

/**
 * Map a /api/biblissima/suggest entry to the url-datatype tile value.
 * Storage policy (spec §3.1): label EN when Biblissima has one, else FR;
 * portal ARK when P129 exists, else entity URI. Tolerates the pre-upgrade
 * cached payload shape (enriched fields absent).
 */
export function mapSuggestItemToValue(item) {
    const label = (item.label_en || item.label || item.text || '').trim();
    const url = (item.portal_url || item.entity_uri || (ENTITY_URI_BASE + item.id)).trim();
    return { url: url, url_label: label };
}

/**
 * Build the dropdown row as a DOM node — never as an HTML string: labels
 * and descriptions come from a third-party Wikibase.
 */
export function renderSuggestItem(item, enBadgePrefix) {
    if (!item.id) {
        return item.text; // select2 "Searching…" / message rows
    }
    const container = document.createElement('div');
    const strong = document.createElement('strong');
    strong.textContent = item.text || '';
    container.appendChild(strong);
    if (item.label_en && item.label_en !== item.text) {
        const badge = document.createElement('span');
        badge.className = 'label label-info biblissima-en-badge';
        badge.textContent = (enBadgePrefix || 'EN: ') + item.label_en;
        container.appendChild(document.createTextNode(' '));
        container.appendChild(badge);
    }
    if (item.description) {
        container.appendChild(document.createElement('br'));
        const small = document.createElement('small');
        small.className = 'text-muted';
        small.textContent = item.description;
        container.appendChild(small);
    }
    return container;
}

/** True when the URL belongs to the Biblissima referential (portal or entity). */
export function isReferentialUrl(url) {
    if (!url) {
        return false;
    }
    return url.indexOf(PORTAL_BASE) === 0 || url.indexOf(ENTITY_URI_BASE) === 0;
}
