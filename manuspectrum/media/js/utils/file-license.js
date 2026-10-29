/**
 * Licence of a stored file and the notice shown next to it.
 *
 * The catalogue comes from `arches.translations.licenseCatalogue`
 * (`templates/javascript.htm`, built from `constants/licenses.py`), labels
 * already in the page language. Resolution mirrors `licenses.resolve()`: a
 * missing or unknown licence shows the default, a catalogue id always shows
 * the catalogue URL, and a custom licence is kept only with a label and an
 * http(s) URL, so no stored value reaches an `href` unchecked.
 */

import ko from 'knockout';

const WEB_URL = /^https?:\/\/[^/\s?#]+/i;

const text = (value) => {
    const unwrapped = ko.unwrap(value);
    return typeof unwrapped === 'string' ? unwrapped.trim() : '';
};

export const catalogueFrom = (raw) => {
    const licenses = Array.isArray(raw?.licenses) ? raw.licenses : [];
    return {
        defaultId: raw?.default,
        customId: raw?.custom,
        licenses,
        byId: new Map(licenses.map((entry) => [entry.id, entry])),
    };
};

const fromCatalogue = (entry) => entry && { id: entry.id, label: entry.label, url: entry.url };

/** `{id, label, url}` to display for a stored licence, or null without a catalogue. */
export const resolveLicense = (license, catalogue) => {
    const stored = ko.toJS(license);
    const id = stored && typeof stored === 'object' ? stored.id : undefined;
    if (id && id === catalogue.customId) {
        const label = text(stored.label);
        const url = text(stored.url);
        if (label && WEB_URL.test(url)) {
            return { id, label, url };
        }
    } else if (catalogue.byId.has(id)) {
        return fromCatalogue(catalogue.byId.get(id));
    }
    return fromCatalogue(catalogue.byId.get(catalogue.defaultId)) || null;
};

const localizedValue = (field, lang) => text(ko.unwrap(field)?.[lang]?.value);

/** Title, © attribution and linked licence, empty parts left out. */
export const noticeParts = (entry, catalogue, lang) => {
    const parts = [];
    const title = localizedValue(entry.title, lang);
    if (title) {
        parts.push({ text: title });
    }
    const attribution = localizedValue(entry.attribution, lang);
    if (attribution) {
        parts.push({ text: attribution.startsWith('©') ? attribution : `© ${attribution}` });
    }
    const license = resolveLicense(entry.license, catalogue);
    if (license) {
        parts.push({ text: license.label, url: license.url });
    }
    return parts;
};

/** File name and linked licence, for the report row of one file. */
export const reportParts = (entry, catalogue) => {
    const parts = [];
    const name = text(entry.name);
    if (name) {
        parts.push({ text: name });
    }
    const license = resolveLicense(entry.license, catalogue);
    if (license) {
        parts.push({ text: license.label, url: license.url });
    }
    return parts;
};

/** The `license` value stored for a choice made in the form, or null without a catalogue. */
export const licenseToStore = (id, label, url, catalogue) => {
    if (id && id === catalogue.customId) {
        return { id, label: text(label), url: text(url) };
    }
    const entry = catalogue.byId.get(id) || catalogue.byId.get(catalogue.defaultId);
    return entry ? { id: entry.id, url: entry.url } : null;
};

/**
 * Stores `value` on `entry.license`, held in one observable that the tile
 * serialises as the plain object.
 *
 * The file array is never notified: its subscribers re-mount the File Viewer
 * renderer. The first write replaces whatever the key held (absent, or the
 * observables knockout-mapping made of a stored licence) and wakes
 * `tile._tileData` once, as `viewmodels/provisional-tile.js` does, so
 * `tile.dirty` re-reads the data and tracks the new observable; later writes
 * go through that observable only.
 */
export const writeLicense = (entry, value, tile) => {
    if (!value) {
        return;
    }
    if (ko.isWriteableObservable(entry.license)) {
        entry.license(value);
        return;
    }
    entry.license = ko.observable(value);
    if (tile && ko.isObservable(tile._tileData)) {
        tile._tileData.valueHasMutated();
    }
};

/**
 * The stored licence of `entry` as a plain object. Read inside a computed, it
 * also follows `tile._tileData`, so a key another instance adds is seen.
 */
export const readLicense = (entry, tile) => {
    if (tile && ko.isObservable(tile._tileData)) {
        tile._tileData();
    }
    return ko.toJS(entry.license);
};
