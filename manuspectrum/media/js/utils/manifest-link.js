/**
 * The public IIIF URL of a stored manifest reference: `<origin>/iiif/manifest/<uuid>`,
 * language-neutral and readable cross-origin. A reference is the bare
 * `/manifest/<uuid>` a tile stores, Arches' `/<lang>/manifest/<uuid>`, or the
 * IIIF path, relative or on the site's own origin. Anything else (an external
 * manifest URL) gives null.
 */
const LOCAL =
    /^(?:\/(?:[a-z]{2}(?:-[a-zA-Z]+)?))?(?:\/iiif)?\/manifest\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/?$/i;

export const iiifManifestUrl = (value, origin) => {
    if (typeof value !== 'string' || !value) return null;
    const own = String(origin).replace(/\/+$/, '');
    const path = value.startsWith(`${own}/`) ? value.slice(own.length) : value;
    if (!path.startsWith('/')) return null;
    const match = LOCAL.exec(path);
    return match ? `${own}/iiif/manifest/${match[1].toLowerCase()}` : null;
};
