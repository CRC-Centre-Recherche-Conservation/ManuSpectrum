import { onScopeDispose, ref, watch } from "vue";

import {
    readStorage,
    writeStorage,
} from "@/manuspectrum/public/safe-storage.ts";
import {
    BASKET_LIMIT,
    kindOf,
    normalizeItemKey,
} from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";

import type { Ref } from "vue";
import type { ExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import type { BasketItem } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export const BASKET_STORAGE_KEY = "ms-explorer-basket-v1";
/** When this browser last changed the Selection (milliseconds since the epoch). */
export const BASKET_TOUCHED_KEY = "ms-explorer-basket-touched-v1";
/** Days a Selection stays stored without any change. */
export const SELECTION_MAX_AGE_DAYS = 90;

const DAY_MS = 24 * 60 * 60 * 1000;

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
 * another tab's value never writes it back; each write dates the Selection
 * in `ms-explorer-basket-touched-v1`. A `storage` event is adopted as it is,
 * a storage clear (`key` null) empties the Selection. A stored Selection
 * left unchanged for more than `SELECTION_MAX_AGE_DAYS` is emptied on start
 * and `expired` turns true; so it does when another tab empties this tab's
 * Selection for age (the stored date is then past the maximum age). One
 * stored without a date is kept and dated now. Without storage the
 * Selection lives in memory for the page's lifetime.
 */
export function useBasketPersistence(store: ExplorerStore): {
    expired: Ref<boolean>;
} {
    const expired = ref(false);

    function tooOld(): boolean {
        const touched = Number(readStorage(BASKET_TOUCHED_KEY));
        return (
            Number.isFinite(touched) &&
            touched > 0 &&
            Date.now() - touched > SELECTION_MAX_AGE_DAYS * DAY_MS
        );
    }

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
            const items = parseBasket(event.newValue);
            if (items.length === 0 && store.basket.length > 0 && tooOld()) {
                expired.value = true;
            }
            adopt(items);
        }
    }

    let stored = parseBasket(readStorage(BASKET_STORAGE_KEY));
    if (stored.length > 0) {
        const touched = Number(readStorage(BASKET_TOUCHED_KEY));
        if (!Number.isFinite(touched) || touched <= 0) {
            writeStorage(BASKET_TOUCHED_KEY, String(Date.now()));
        } else if (tooOld()) {
            stored = [];
            expired.value = true;
            writeStorage(BASKET_STORAGE_KEY, serializeBasket(stored));
        }
    }
    adopt(stored);

    watch(
        () => serializeBasket(store.basket),
        (serialized) => {
            if (readStorage(BASKET_STORAGE_KEY) !== serialized) {
                writeStorage(BASKET_STORAGE_KEY, serialized);
                writeStorage(BASKET_TOUCHED_KEY, String(Date.now()));
            }
        },
    );

    window.addEventListener("storage", onStorage);
    onScopeDispose(() => window.removeEventListener("storage", onStorage));
    return { expired };
}
