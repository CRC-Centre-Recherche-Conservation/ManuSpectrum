import { onScopeDispose, watch } from "vue";

import {
    readStorage,
    writeStorage,
} from "@/manuspectrum/public/safe-storage.ts";
import {
    BASKET_LIMIT,
    kindOf,
    normalizeItemKey,
} from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";

import type { ExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import type { BasketItem } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export const BASKET_STORAGE_KEY = "ms-explorer-basket-v1";

/** Stored Selection: valid, unique keys at unique in-range slots, in slot order; anything else is dropped. */
export function parseBasket(raw: string | null): BasketItem[] {
    if (!raw) {
        return [];
    }
    let parsed: unknown;
    try {
        parsed = JSON.parse(raw);
    } catch {
        return [];
    }
    if (!Array.isArray(parsed)) {
        return [];
    }
    const items: BasketItem[] = [];
    const keys = new Set<string>();
    const slots = new Set<number>();
    for (const entry of parsed.slice(0, BASKET_LIMIT * 2)) {
        if (typeof entry !== "object" || entry === null) {
            continue;
        }
        const { key, slot } = entry as { key?: unknown; slot?: unknown };
        const normalized =
            typeof key === "string" ? normalizeItemKey(key) : null;
        if (
            normalized === null ||
            keys.has(normalized) ||
            typeof slot !== "number" ||
            !Number.isInteger(slot) ||
            slot < 0 ||
            slot >= BASKET_LIMIT ||
            slots.has(slot)
        ) {
            continue;
        }
        keys.add(normalized);
        slots.add(slot);
        items.push({ key: normalized, kind: kindOf(normalized), slot });
    }
    return items.sort((a, b) => a.slot - b.slot).slice(0, BASKET_LIMIT);
}

export function serializeBasket(items: readonly BasketItem[]): string {
    return JSON.stringify(
        [...items]
            .sort((a, b) => a.slot - b.slot)
            .map(({ key, slot }) => ({ key, slot })),
    );
}

/**
 * Keep the Selection in `ms-explorer-basket-v1` and in step with other tabs.
 *
 * A change is written only when the stored string differs, so adopting
 * another tab's value never writes it back. A `storage` event is adopted as
 * it is, a storage clear (`key` null) empties the Selection. Without storage
 * the Selection lives in memory for the page's lifetime.
 */
export function useBasketPersistence(store: ExplorerStore): void {
    function adopt(items: BasketItem[]): void {
        if (serializeBasket(items) !== serializeBasket(store.basket)) {
            store.$patch((state) => {
                state.basket = items;
            });
        }
    }

    function onStorage(event: StorageEvent): void {
        if (event.key === null) {
            adopt([]);
        } else if (event.key === BASKET_STORAGE_KEY) {
            adopt(parseBasket(event.newValue));
        }
    }

    adopt(parseBasket(readStorage(BASKET_STORAGE_KEY)));

    watch(
        () => serializeBasket(store.basket),
        (serialized) => {
            if (readStorage(BASKET_STORAGE_KEY) !== serialized) {
                writeStorage(BASKET_STORAGE_KEY, serialized);
            }
        },
    );

    window.addEventListener("storage", onStorage);
    onScopeDispose(() => window.removeEventListener("storage", onStorage));
}
