// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import {
    mapSuggestItemToValue,
    renderSuggestItem,
    isReferentialUrl,
    isPortalArk,
} from './biblissima-concept-utils.js';

// Test fixtures only — the production module carries no real Biblissima
// URL literal; these bases are injected explicitly into every call below,
// mirroring how the widget threads them from Django settings at runtime.
const ENTITY_BASE = 'https://data.biblissima.fr/entity';
const PORTAL_BASE = 'https://portail.biblissima.fr/';

const ARK = 'https://portail.biblissima.fr/fr/ark:/43093/desc' + 'a'.repeat(40);
const ENTITY = 'https://data.biblissima.fr/entity/Q291430';

describe('mapSuggestItemToValue', () => {
    it('prefers the English label, falls back to French', () => {
        expect(mapSuggestItemToValue({
            id: 'Q1', label: 'dragon', label_en: 'Dragon',
            portal_url: ARK, entity_uri: ENTITY,
        }, ENTITY_BASE)).toEqual({ url: ARK, url_label: 'Dragon' });
        expect(mapSuggestItemToValue({
            id: 'Q1', label: 'dragon', label_en: null,
            portal_url: ARK, entity_uri: ENTITY,
        }, ENTITY_BASE).url_label).toBe('dragon');
    });

    it('prefers the portal ARK, falls back to entity URI, then builds from id', () => {
        expect(mapSuggestItemToValue({
            id: 'Q1', label: 'x', portal_url: null, entity_uri: ENTITY,
        }, ENTITY_BASE).url).toBe(ENTITY);
        // old cached payload shape: enriched fields entirely absent
        expect(mapSuggestItemToValue({ id: 'Q291430', label: 'x' }, ENTITY_BASE).url)
            .toBe(ENTITY);
    });

    it('trims url and label', () => {
        const value = mapSuggestItemToValue({
            id: 'Q1', label: ' dragon ', label_en: null,
            portal_url: ` ${ARK} `, entity_uri: ENTITY,
        }, ENTITY_BASE);
        expect(value.url).toBe(ARK);
        expect(value.url_label).toBe('dragon');
    });

    it('builds the fallback url from an injected entity URI base', () => {
        expect(mapSuggestItemToValue(
            { id: 'Q1', label: 'x' }, 'https://example.test/e',
        ).url).toBe('https://example.test/e/Q1');
    });

    it('does not produce "undefined/id" when the entity URI base is missing', () => {
        expect(mapSuggestItemToValue({ id: 'Q1', label: 'x' }).url).toBe('');
        expect(mapSuggestItemToValue({ id: 'Q1', label: 'x' }, null).url).toBe('');
    });
});

describe('renderSuggestItem', () => {
    it('renders hostile labels inert (no HTML injection)', () => {
        const el = renderSuggestItem({
            id: 'Q1',
            text: '<img src=x onerror=alert(1)>',
            description: '<script>alert(2)</script>',
        }, 'EN: ');
        expect(el.querySelector('img')).toBeNull();
        expect(el.querySelector('script')).toBeNull();
        expect(el.textContent).toContain('<img src=x onerror=alert(1)>');
    });

    it('shows the EN badge only when label_en differs from the shown label', () => {
        const withBadge = renderSuggestItem(
            { id: 'Q1', text: 'ange', label_en: 'angel' }, 'EN: ');
        expect(withBadge.querySelector('.biblissima-en-badge').textContent)
            .toBe('EN: angel');
        const sameLabel = renderSuggestItem(
            { id: 'Q1', text: 'dragon', label_en: 'dragon' }, 'EN: ');
        expect(sameLabel.querySelector('.biblissima-en-badge')).toBeNull();
    });

    it('passes through loading rows untouched', () => {
        expect(renderSuggestItem({ text: 'Searching…' }, 'EN: '))
            .toBe('Searching…');
    });
});

describe('isReferentialUrl', () => {
    it('recognizes portal ARKs and entity URIs, rejects the rest', () => {
        expect(isReferentialUrl(ARK, PORTAL_BASE, ENTITY_BASE)).toBe(true);
        expect(isReferentialUrl(ENTITY, PORTAL_BASE, ENTITY_BASE)).toBe(true);
        expect(isReferentialUrl('https://example.org/x', PORTAL_BASE, ENTITY_BASE)).toBe(false);
        expect(isReferentialUrl(null, PORTAL_BASE, ENTITY_BASE)).toBe(false);
    });

    it('recognizes injected portal/entity bases, rejects non-matching urls', () => {
        expect(isReferentialUrl(
            'https://example.test/e/Q1', 'https://example.test/p', 'https://example.test/e',
        )).toBe(true);
        expect(isReferentialUrl(
            'https://other.test/x', 'https://example.test/p', 'https://example.test/e',
        )).toBe(false);
    });

    it('does not throw and does not match when a base is missing', () => {
        expect(isReferentialUrl(ARK)).toBe(false);
        expect(isReferentialUrl(ARK, undefined, undefined)).toBe(false);
        expect(isReferentialUrl(ARK, null, ENTITY_BASE)).toBe(false);
    });
});

describe('isPortalArk', () => {
    it('recognizes a persistent portal ARK', () => {
        expect(isPortalArk(ARK, PORTAL_BASE)).toBe(true);
    });

    it('rejects the entity-URI fallback (no persistent portal ARK)', () => {
        expect(isPortalArk(ENTITY, PORTAL_BASE)).toBe(false);
    });

    it('rejects null urls', () => {
        expect(isPortalArk(null, PORTAL_BASE)).toBe(false);
    });

    it('does not throw and does not match when the portal base is missing', () => {
        expect(isPortalArk(ARK)).toBe(false);
        expect(isPortalArk(ARK, undefined)).toBe(false);
        expect(isPortalArk(ARK, null)).toBe(false);
    });
});
