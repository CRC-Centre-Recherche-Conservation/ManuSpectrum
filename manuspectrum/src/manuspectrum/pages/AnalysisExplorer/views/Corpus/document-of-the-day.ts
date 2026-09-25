const FNV_OFFSET = 0x811c9dc5;
const FNV_PRIME = 0x01000193;

/** The reader's local day as `YYYY-MM-DD`. */
export function localDay(date: Date): string {
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${date.getFullYear()}-${month}-${day}`;
}

/**
 * The position (from 0) of the document of the day among `count` documents:
 * a hash (FNV-1a) of the local day, so every reader of that day gets the same
 * one and the next day another. Null when there is none.
 */
export function dayIndex(date: Date, count: number): number | null {
    if (count <= 0) return null;
    let hash = FNV_OFFSET;
    for (const character of localDay(date)) {
        hash ^= character.charCodeAt(0);
        hash = Math.imul(hash, FNV_PRIME) >>> 0;
    }
    return hash % count;
}
