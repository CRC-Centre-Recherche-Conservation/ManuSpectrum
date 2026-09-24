import { beforeAll, vi } from 'vitest';

beforeAll(() => {
    vi.mock('arches', () => ({
        default: '',
    }));

    vi.mock('vue3-gettext', async (importOriginal) => ({
        ...(await importOriginal<typeof import('vue3-gettext')>()),
        useGettext: () => ({
            $gettext: (text: string) => text,
            $pgettext: (_context: string, text: string) => text,
            $ngettext: (singular: string, plural: string, count: number) =>
                count === 1 ? singular : plural,
            interpolate: (text: string, values: Record<string, unknown> = {}) =>
                text.replace(/%\{\s*(\w+)\s*\}/g, (match, name: string) =>
                    name in values ? String(values[name]) : match,
                ),
            current: 'en',
        }),
    }));
});
