import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, nextTick } from "vue";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    BASKET_STORAGE_KEY,
    BASKET_TOUCHED_KEY,
    SELECTION_MAX_AGE_DAYS,
    parseBasket,
    serializeBasket,
    useBasketPersistence,
} from "@/manuspectrum/pages/AnalysisExplorer/store/persistence.ts";

import type { ExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

const ORIGINAL = Object.getOwnPropertyDescriptor(window, "localStorage");

function key(n: number): string {
    return `ch:00000000-0000-4000-8000-${String(n).padStart(12, "0")}:-`;
}

const DAY_MS = 24 * 60 * 60 * 1000;

function mountPersistence(): {
    store: ExplorerStore;
    expired: boolean;
    unmount: () => void;
} {
    const store = useExplorerStore();
    let expired = false;
    const wrapper = mount(
        defineComponent({
            setup() {
                expired = useBasketPersistence(store).expired;
                return () => h("div");
            },
        }),
    );
    return { store, expired, unmount: () => wrapper.unmount() };
}

function basketWrites(setItem: { mock: { calls: unknown[][] } }): number {
    return setItem.mock.calls.filter((call) => call[0] === BASKET_STORAGE_KEY)
        .length;
}

beforeEach(() => {
    setActivePinia(createPinia());
    window.localStorage.clear();
});

afterEach(() => {
    vi.restoreAllMocks();
    if (ORIGINAL) {
        Object.defineProperty(window, "localStorage", ORIGINAL);
    } else {
        Reflect.deleteProperty(window, "localStorage");
    }
});

describe("parseBasket", () => {
    it("reads a valid stored Selection in slot order", () => {
        const raw = JSON.stringify([
            { key: key(2), slot: 4 },
            { key: key(1), slot: 0 },
        ]);
        expect(parseBasket(raw)).toEqual([
            { key: key(1), kind: "characterization", slot: 0 },
            { key: key(2), kind: "characterization", slot: 4 },
        ]);
    });

    it("drops malformed JSON, invalid keys, duplicate keys or slots and out-of-range slots", () => {
        expect(parseBasket("{not json")).toEqual([]);
        expect(parseBasket(JSON.stringify({ key: key(1) }))).toEqual([]);
        const raw = JSON.stringify([
            { key: key(1), slot: 0 },
            { key: key(1), slot: 1 },
            { key: key(2), slot: 0 },
            { key: "nope", slot: 2 },
            { key: key(3), slot: 30 },
            { key: key(4), slot: 1.5 },
            null,
            { key: key(5), slot: 3 },
        ]);
        expect(parseBasket(raw).map((item) => item.key)).toEqual([
            key(1),
            key(5),
        ]);
    });

    it("serializes keys and slots only", () => {
        expect(
            serializeBasket([
                { key: key(1), kind: "characterization", slot: 0 },
            ]),
        ).toBe(JSON.stringify([{ key: key(1), slot: 0 }]));
    });
});

describe("useBasketPersistence", () => {
    it("loads the stored Selection on start", () => {
        window.localStorage.setItem(
            BASKET_STORAGE_KEY,
            JSON.stringify([{ key: key(1), slot: 2 }]),
        );
        const { store } = mountPersistence();
        expect(store.basket).toEqual([
            { key: key(1), kind: "characterization", slot: 2 },
        ]);
    });

    it("writes a change once and never an unchanged value", async () => {
        const { store } = mountPersistence();
        const setItem = vi.spyOn(Storage.prototype, "setItem");
        store.addToBasket(key(1));
        await nextTick();
        expect(basketWrites(setItem)).toBe(1);
        store.addToBasket(key(1));
        await nextTick();
        expect(basketWrites(setItem)).toBe(1);
    });

    it("adopts the other tab's Selection as it is", async () => {
        const { store } = mountPersistence();
        store.addToBasket(key(9));
        const incoming = JSON.stringify([{ key: key(1), slot: 5 }]);
        window.localStorage.setItem(BASKET_STORAGE_KEY, incoming);
        const setItem = vi.spyOn(Storage.prototype, "setItem");
        window.dispatchEvent(
            new StorageEvent("storage", {
                key: BASKET_STORAGE_KEY,
                newValue: incoming,
            }),
        );
        await nextTick();
        expect(store.basket).toEqual([
            { key: key(1), kind: "characterization", slot: 5 },
        ]);
        expect(setItem).not.toHaveBeenCalled();
    });

    it("ignores other keys and empties on a storage clear", async () => {
        const { store } = mountPersistence();
        store.addToBasket(key(1));
        window.dispatchEvent(
            new StorageEvent("storage", { key: "other", newValue: "[]" }),
        );
        expect(store.basket).toHaveLength(1);
        window.dispatchEvent(
            new StorageEvent("storage", { key: null, newValue: null }),
        );
        expect(store.basket).toEqual([]);
    });

    it("keeps the Selection in memory when storage throws", async () => {
        Object.defineProperty(window, "localStorage", {
            configurable: true,
            get() {
                throw new DOMException("blocked", "SecurityError");
            },
        });
        expect(() => mountPersistence()).not.toThrow();
        const store = useExplorerStore();
        store.addToBasket(key(1));
        await nextTick();
        expect(store.basket).toHaveLength(1);
    });

    it("stops listening once unmounted", () => {
        const { store, unmount } = mountPersistence();
        unmount();
        window.dispatchEvent(
            new StorageEvent("storage", {
                key: BASKET_STORAGE_KEY,
                newValue: JSON.stringify([{ key: key(1), slot: 0 }]),
            }),
        );
        expect(store.basket).toEqual([]);
    });
});

describe("Selection expiry", () => {
    const NOW = Date.UTC(2026, 8, 27);

    beforeEach(() => {
        vi.useFakeTimers();
        vi.setSystemTime(NOW);
        window.localStorage.setItem(
            BASKET_STORAGE_KEY,
            JSON.stringify([{ key: key(1), slot: 0 }]),
        );
    });

    afterEach(() => vi.useRealTimers());

    it("drops a Selection left unchanged for more than the maximum age, and says so", () => {
        window.localStorage.setItem(
            BASKET_TOUCHED_KEY,
            String(NOW - SELECTION_MAX_AGE_DAYS * DAY_MS - 1),
        );
        const { store, expired } = mountPersistence();
        expect(expired).toBe(true);
        expect(store.basket).toEqual([]);
        expect(window.localStorage.getItem(BASKET_STORAGE_KEY)).toBe("[]");
    });

    it("keeps a Selection changed within the maximum age", () => {
        window.localStorage.setItem(
            BASKET_TOUCHED_KEY,
            String(NOW - SELECTION_MAX_AGE_DAYS * DAY_MS),
        );
        const { store, expired } = mountPersistence();
        expect(expired).toBe(false);
        expect(store.basket).toHaveLength(1);
    });

    it("keeps a Selection stored without a date and dates it now", () => {
        const { store, expired } = mountPersistence();
        expect(expired).toBe(false);
        expect(store.basket).toHaveLength(1);
        expect(window.localStorage.getItem(BASKET_TOUCHED_KEY)).toBe(
            String(NOW),
        );
    });

    it("dates every change of this tab, never a read or another tab's value", async () => {
        window.localStorage.setItem(BASKET_TOUCHED_KEY, String(NOW - DAY_MS));
        const { store } = mountPersistence();
        expect(window.localStorage.getItem(BASKET_TOUCHED_KEY)).toBe(
            String(NOW - DAY_MS),
        );
        const incoming = JSON.stringify([{ key: key(2), slot: 1 }]);
        window.localStorage.setItem(BASKET_STORAGE_KEY, incoming);
        window.dispatchEvent(
            new StorageEvent("storage", {
                key: BASKET_STORAGE_KEY,
                newValue: incoming,
            }),
        );
        await nextTick();
        expect(window.localStorage.getItem(BASKET_TOUCHED_KEY)).toBe(
            String(NOW - DAY_MS),
        );
        vi.setSystemTime(NOW + 1000);
        store.addToBasket(key(3));
        await nextTick();
        expect(window.localStorage.getItem(BASKET_TOUCHED_KEY)).toBe(
            String(NOW + 1000),
        );
    });
});
