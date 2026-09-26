/** Image URLs that failed to load in this tab; a card does not ask for them again. */
const failed = new Set<string>();

export function hasImageFailed(url: string): boolean {
    return failed.has(url);
}

export function markImageFailed(url: string): void {
    failed.add(url);
}
