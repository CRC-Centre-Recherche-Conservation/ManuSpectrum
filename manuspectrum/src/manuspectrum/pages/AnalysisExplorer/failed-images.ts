/** How long a card leaves an image that failed to load before asking for it again. */
export const IMAGE_RETRY_AFTER_MS = 60_000;

/** When each image URL last failed to load in this tab. */
const failedAt = new Map<string, number>();

/** Whether `url` failed to load less than `IMAGE_RETRY_AFTER_MS` ago; a card does not ask for it meanwhile. */
export function hasImageFailed(url: string): boolean {
    const at = failedAt.get(url);
    if (at === undefined) return false;
    if (Date.now() - at < IMAGE_RETRY_AFTER_MS) return true;
    failedAt.delete(url);
    return false;
}

export function markImageFailed(url: string): void {
    failedAt.set(url, Date.now());
}
