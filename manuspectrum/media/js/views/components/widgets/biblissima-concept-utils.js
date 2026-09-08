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
 * True when `url` starts with `base` on a path boundary — it is `base`
 * itself, or the next character after `base` is '/'. Rejects a bare-prefix
 * false positive like `…/ark:/43093attacker/foo` matching `…/ark:/43093`.
 * When `base` already ends with '/', the slash is the boundary, so any URL
 * below it matches. A falsy base never matches (and never throws).
 */
function startsWithBase(url, base) {
    return (
        !!base &&
        url.indexOf(base) === 0 &&
        (base.charAt(base.length - 1) === '/' ||
            url.length === base.length ||
            url.charAt(base.length) === '/')
    );
}

/**
 * True when the URL belongs to the Biblissima referential (portal or
 * entity). `portalBase`/`entityUriBase` are the Django-settings-sourced
 * values passed in by the widget; a missing base must not throw and must
 * not match.
 */
export function isReferentialUrl(url, portalBase, entityUriBase) {
    return Boolean(url) && (
        startsWithBase(url, portalBase) || startsWithBase(url, entityUriBase)
    );
}

/**
 * True when the URL is a persistent Biblissima portal ARK specifically
 * (not merely the entity-URI fallback). `portalBase` is the
 * Django-settings-sourced value passed in by the widget; a missing base
 * must not throw and must not match.
 */
export function isPortalArk(url, portalBase) {
    return Boolean(url) && startsWithBase(url, portalBase);
}
