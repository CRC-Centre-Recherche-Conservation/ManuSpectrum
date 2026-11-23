import { describe, expect, it } from 'vitest';

import { iiifManifestUrl } from './manifest-link.js';

const ORIGIN = 'https://site.example';
const ID = '3f2a9c1e-5b7d-4e8a-9c3b-1a2b3c4d5e6f';
const IIIF = `${ORIGIN}/iiif/manifest/${ID}`;

describe('manifest-link', () => {
    it('gives the IIIF URL of every local reference', () => {
        for (const value of [
            `/manifest/${ID}`,
            `/en/manifest/${ID}`,
            `/fr/manifest/${ID}`,
            `/iiif/manifest/${ID}`,
            `${ORIGIN}/manifest/${ID}`,
            `${ORIGIN}/fr/manifest/${ID}`,
            `${ORIGIN}/iiif/manifest/${ID}`,
            `/manifest/${ID.toUpperCase()}`,
        ]) {
            expect(iiifManifestUrl(value, ORIGIN)).toBe(IIIF);
        }
    });

    it('leaves an external manifest URL alone', () => {
        expect(iiifManifestUrl(`https://other.example/manifest/${ID}`, ORIGIN)).toBeNull();
        expect(iiifManifestUrl('https://example.org/iiif/ms60/manifest', ORIGIN)).toBeNull();
    });

    it('ignores what is not a manifest reference', () => {
        for (const value of [null, undefined, '', ID, '/manifest/12', `/files/manifest/${ID}`]) {
            expect(iiifManifestUrl(value, ORIGIN)).toBeNull();
        }
    });
});
