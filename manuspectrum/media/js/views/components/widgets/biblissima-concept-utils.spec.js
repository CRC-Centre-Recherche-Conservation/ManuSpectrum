// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import {
    mapSuggestItemToValue,
    renderSuggestItem,
    isReferentialUrl,
} from './biblissima-concept-utils.js';

const ARK = 'https://portail.biblissima.fr/fr/ark:/43093/desc' + 'a'.repeat(40);
const ENTITY = 'https://data.biblissima.fr/entity/Q291430';

describe('mapSuggestItemToValue', () => {
    it('prefers the English label, falls back to French', () => {
        expect(mapSuggestItemToValue({
            id: 'Q1', label: 'dragon', label_en: 'Dragon',
            portal_url: ARK, entity_uri: ENTITY,
        })).toEqual({ url: ARK, url_label: 'Dragon' });
        expect(mapSuggestItemToValue({
            id: 'Q1', label: 'dragon', label_en: null,
            portal_url: ARK, entity_uri: ENTITY,
        }).url_label).toBe('dragon');
    });

    it('prefers the portal ARK, falls back to entity URI, then builds from id', () => {
        expect(mapSuggestItemToValue({
            id: 'Q1', label: 'x', portal_url: null, entity_uri: ENTITY,
        }).url).toBe(ENTITY);
        // old cached payload shape: enriched fields entirely absent
        expect(mapSuggestItemToValue({ id: 'Q291430', label: 'x' }).url)
            .toBe(ENTITY);
    });

    it('trims url and label', () => {
        const value = mapSuggestItemToValue({
            id: 'Q1', label: ' dragon ', label_en: null,
            portal_url: ` ${ARK} `, entity_uri: ENTITY,
        });
        expect(value.url).toBe(ARK);
        expect(value.url_label).toBe('dragon');
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
        expect(isReferentialUrl(ARK)).toBe(true);
        expect(isReferentialUrl(ENTITY)).toBe(true);
        expect(isReferentialUrl('https://example.org/x')).toBe(false);
        expect(isReferentialUrl(null)).toBe(false);
    });
});
