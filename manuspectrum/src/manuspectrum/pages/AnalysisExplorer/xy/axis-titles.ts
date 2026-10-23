/**
 * The « first stored title » rule of the charts that draw spectra of
 * several configurations together: the first title, in the order given,
 * that holds text, trimmed; null when none does.
 */
export function firstStoredTitle(
    values: readonly (string | null | undefined)[],
): string | null {
    for (const value of values) {
        const text = value?.trim();
        if (text) return text;
    }
    return null;
}
