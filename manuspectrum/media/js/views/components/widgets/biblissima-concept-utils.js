/**
 * Pure helpers for the biblissima-concept widget — kept import-free so
 * vitest can exercise them without the webpack-alias stubs (the mocked
 * WidgetViewModel/bindings make the widget viewmodel itself untestable).
 */

/**
 * Map a /api/biblissima/suggest entry to the url-datatype tile value.
 * Storage policy (spec §3.1): label EN when Biblissima has one, else FR;
 * portal ARK when P129 exists, else entity URI. Tolerates the pre-upgrade
 * cached payload shape (enriched fields absent).
 *
 * `entityUriBase` is the Django-settings-sourced Biblissima entity base
 * (no trailing slash), passed in by the widget. The backend always sends
 * `entity_uri` now, so the `entityUriBase` fallback branch is a rare
 * defensive path; when `entityUriBase` is missing it must NOT produce
 * "undefined/Q1" — hence the guard.
 */
export function mapSuggestItemToValue(item, entityUriBase) {
    const label = (item.label_en || item.label || item.text || '').trim();
    const url = (
        item.portal_url || item.entity_uri || (entityUriBase ? `${entityUriBase}/${item.id}` : '')
    ).trim();
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

/**
 * True when the URL belongs to the Biblissima referential (portal or
 * entity). `portalBase`/`entityUriBase` are the Django-settings-sourced
 * values passed in by the widget; a missing base must not throw and must
 * not match.
 */
export function isReferentialUrl(url, portalBase, entityUriBase) {
    return Boolean(url) && (
        (!!portalBase && url.indexOf(portalBase) === 0) ||
        (!!entityUriBase && url.indexOf(entityUriBase) === 0)
    );
}

/**
 * True when the URL is a persistent Biblissima portal ARK specifically
 * (not merely the entity-URI fallback). `portalBase` is the
 * Django-settings-sourced value passed in by the widget; a missing base
 * must not throw and must not match.
 */
export function isPortalArk(url, portalBase) {
    return Boolean(url) && !!portalBase && url.indexOf(portalBase) === 0;
}
