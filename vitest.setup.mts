import { beforeAll, vi } from 'vitest';

beforeAll(() => {
    vi.mock('arches', () => ({
        default: '',
    }));

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
