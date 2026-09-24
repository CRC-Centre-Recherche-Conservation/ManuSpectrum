import { beforeAll, vi } from 'vitest';

beforeAll(() => {
    vi.mock('arches', () => ({
        default: '',
    }));

    // Arches' vendored plugin (aliased in vitest.config.mts) registers itself
    // as an AMD module via `define`, which Vitest cannot load.
    vi.mock('leaflet-side-by-side', () => ({}));

    // The real plugin with an empty catalogue: source text in, interpolation
    // (HTML escaping included) exactly as in the browser.
    vi.mock('vue3-gettext', async (importOriginal) => {
        const original = await importOriginal<typeof import('vue3-gettext')>();
        const gettext = original.createGettext({
            translations: {},
            defaultLanguage: 'en',
            silent: true,
        });
        return { ...original, useGettext: () => gettext };
    });
});
