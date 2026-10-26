import { describe, expect, it } from 'vitest';

import { imageUrl, infoJsonUrl } from './iiif-image.js';

describe('iiif-image', () => {
    it('builds the info.json URL of a service, trailing slash or not', () => {
        expect(infoJsonUrl('https://iiif.example/image/f1')).toBe('https://iiif.example/image/f1/info.json');
        expect(infoJsonUrl('https://iiif.example/image/f1/')).toBe('https://iiif.example/image/f1/info.json');
    });

    it('builds an image request, full and max by default', () => {
        expect(imageUrl('https://iiif.example/image/f1')).toBe('https://iiif.example/image/f1/full/max/0/default.jpg');
        expect(imageUrl('https://iiif.example/image/f1/', { size: '!2048,2048' })).toBe('https://iiif.example/image/f1/full/!2048,2048/0/default.jpg');
        expect(imageUrl('https://iiif.example/image/f1', { region: '10,20,300,400', size: ',96' })).toBe('https://iiif.example/image/f1/10,20,300,400/,96/0/default.jpg');
    });
});
