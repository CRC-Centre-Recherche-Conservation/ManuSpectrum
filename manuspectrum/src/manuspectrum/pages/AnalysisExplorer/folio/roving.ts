export interface Placed {
    id: string;
    lat: number;
    lng: number;
}

/**
 * Keyboard order of the markers: rows from the top of the page down, left to
 * right inside a row. Rows are `band`-high bins of `lat`; markers in the same
 * `band`-high row share a row.
 */
export function readingOrder(items: readonly Placed[], band = 1): string[] {
    return [...items]
        .sort((a, b) => {
            const rowA = Math.round(-a.lat / band);
            const rowB = Math.round(-b.lat / band);
            return rowA - rowB || a.lng - b.lng || a.id.localeCompare(b.id);
        })
        .map((item) => item.id);
}

/** The marker an arrow, Home or End key moves to; null for any other key or no marker. */
export function nextId(
    order: readonly string[],
    current: string | null,
    key: string,
): string | null {
    if (order.length === 0) return null;
    const index = current === null ? -1 : order.indexOf(current);
    switch (key) {
        case "ArrowRight":
        case "ArrowDown":
            return order[Math.min(index + 1, order.length - 1)];
        case "ArrowLeft":
        case "ArrowUp":
            return order[Math.max(index - 1, 0)];
        case "Home":
            return order[0];
        case "End":
            return order[order.length - 1];
        default:
            return null;
    }
}
