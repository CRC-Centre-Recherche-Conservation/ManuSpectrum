import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, nextTick } from "vue";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    BASKET_STORAGE_KEY,
    parseBasket,
    serializeBasket,
    useBasketPersistence,
} from "@/manuspectrum/pages/AnalysisExplorer/store/persistence.ts";

import type { ExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

const ORIGINAL = Object.getOwnPropertyDescriptor(window, "localStorage");

function key(n: number): string {
    return `ch:00000000-0000-4000-8000-${String(n).padStart(12, "0")}:-`;
}

function mountPersistence(): { store: ExplorerStore; unmount: () => void } {
    const store = useExplorerStore();
    const wrapper = mount(
        defineComponent({
            setup() {
                useBasketPersistence(store);
                return () => h("div");
            },
        }),
    );
    return { store, unmount: () => wrapper.unmount() };
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
        expect(setItem).toHaveBeenCalledTimes(1);
        store.addToBasket(key(1));
        await nextTick();
        expect(setItem).toHaveBeenCalledTimes(1);
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
