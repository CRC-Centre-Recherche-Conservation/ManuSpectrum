import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, ref, watch } from "vue";

import { useSelectionToggle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionToggle.ts";
import {
    ANNOUNCE_KEY,
    SELECTION_HINTS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { analysisKey } from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    label,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import type { SelectionToggle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionToggle.ts";

function key(n: number): string {
    return analysisKey(uuid(n));
}

function removeKey(item: string): void {
    useExplorerStore().removeFromBasket(item);
}

function hint(name: string): SelectionHint {
    return { title: label(name), kind: "analysis" };
}

const announce = vi.fn();
const hints = ref(new Map<string, SelectionHint>());
let toggle: SelectionToggle;

function start(): void {
    mount(
        defineComponent({
            setup() {
                toggle = useSelectionToggle();
                return () => h("div");
            },
        }),
        {
            global: {
                provide: {
                    [ANNOUNCE_KEY as symbol]: announce,
                    [SELECTION_HINTS_KEY as symbol]: hints,
                },
            },
        },
    );
}

beforeEach(() => {
    setActivePinia(createPinia());
    announce.mockReset();
    hints.value = new Map();
    start();
    toggle.dismiss();
});

describe("useSelectionToggle", () => {
    it("adds and removes one key, tells its slot, and says it once", () => {
        const store = useExplorerStore();
        toggle.toggle(key(1));
        expect(toggle.isHeld(key(1))).toBe(true);
        expect(toggle.slotOf(key(1))).toBe("A1");
        expect(store.basket).toHaveLength(1);
        toggle.toggle(key(1));
        expect(toggle.isHeld(key(1))).toBe(false);
        expect(toggle.slotOf(key(1))).toBeNull();
        expect(announce).toHaveBeenCalledTimes(2);
        expect(toggle.lastBulk.value).toBeNull();
    });

    it("records the hint before the key enters the Selection", () => {
        const store = useExplorerStore();
        let hintedFirst = false;
        watch(
            () => store.basket.length,
            () => {
                hintedFirst = hints.value.has(key(1));
            },
            { flush: "sync" },
        );
        toggle.toggle(key(1), hint("One"));
        expect(hints.value.get(key(1))?.title.value).toBe("One");
        expect(hintedFirst).toBe(true);
    });

    it("adds the missing keys of a group with one announcement and a status", () => {
        toggle.toggle(key(1));
        announce.mockReset();
        toggle.toggleAll(
            [key(1), key(2), key(3)],
            new Map([[key(2), hint("Two")]]),
        );
        expect(announce).toHaveBeenCalledTimes(1);
        expect(announce.mock.calls[0][0]).toBe(
            "2 analyses added (A2 to A3). Selection: 3 / 30.",
        );
        expect(toggle.lastBulk.value).toEqual({
            kind: "added",
            keys: [key(2), key(3)],
            slots: ["A2", "A3"],
            total: 3,
        });
        expect(hints.value.has(key(2))).toBe(true);
    });

    it("removes a fully held group and undoes it at the same slots", () => {
        const store = useExplorerStore();
        for (const n of [1, 2, 3, 4]) toggle.toggle(key(n));
        announce.mockReset();
        toggle.toggleAll([key(2), key(4)]);
        expect(announce).toHaveBeenCalledTimes(1);
        expect(announce.mock.calls[0][0]).toBe(
            "2 analyses removed from the Selection.",
        );
        expect(toggle.lastBulk.value?.kind).toBe("removed");
        expect(store.basket.map((item) => item.slot)).toEqual([0, 2]);
        toggle.undo();
        expect(
            store.basket.map((item) => [item.key, item.slot]).sort(),
        ).toEqual([1, 2, 3, 4].map((n) => [key(n), n - 1]).sort());
        expect(toggle.lastBulk.value).toBeNull();
    });

    it("undoes an addition", () => {
        const store = useExplorerStore();
        toggle.toggleAll([key(1), key(2)]);
        toggle.undo();
        expect(store.basket).toEqual([]);
        expect(toggle.lastBulk.value).toBeNull();
    });

    it("refuses a group that does not fit and changes nothing", () => {
        const store = useExplorerStore();
        toggle.toggleAll(Array.from({ length: 29 }, (_, n) => key(n + 1)));
        toggle.dismiss();
        announce.mockReset();
        const keys = [key(100), key(101)];
        expect(toggle.blockedReason(keys)).toBe(
            "2 analyses to add, 1 place left",
        );
        toggle.toggleAll(keys);
        expect(store.basket).toHaveLength(29);
        expect(toggle.lastBulk.value).toBeNull();
    });

    it("has no blocked reason for a group that fits or is fully held", () => {
        toggle.toggleAll(Array.from({ length: 30 }, (_, n) => key(n + 1)));
        expect(toggle.blockedReason([key(1), key(2)])).toBeNull();
        expect(toggle.blockedReason([key(200)])).toBe(
            "Selection full (30/30): remove items to add more.",
        );
    });

    it("reports none, some and all", () => {
        toggle.toggle(key(1));
        expect(toggle.stateOf([key(2)])).toBe("none");
        expect(toggle.stateOf([key(1), key(2)])).toBe("some");
        expect(toggle.stateOf([key(1)])).toBe("all");
    });

    it("dismisses the status", () => {
        toggle.toggleAll([key(1), key(2)]);
        toggle.dismiss();
        expect(toggle.lastBulk.value).toBeNull();
    });

    it("empties the Selection in one step and undoes it at the same slots", () => {
        toggle.toggleAll([key(1), key(2), key(3)]);
        removeKey(key(2));
        toggle.clearAll();
        const store = useExplorerStore();
        expect(store.basket).toEqual([]);
        expect(toggle.lastBulk.value).toMatchObject({
            kind: "emptied",
            keys: [key(1), key(3)],
            slots: ["A1", "A3"],
            total: 0,
        });
        expect(announce).toHaveBeenLastCalledWith("Selection emptied (2).");
        toggle.undo();
        expect(store.basket.map((item) => [item.key, item.slot])).toEqual([
            [key(1), 0],
            [key(3), 2],
        ]);
        expect(toggle.lastBulk.value).toBeNull();
    });

    it("does nothing to empty an empty Selection", () => {
        toggle.clearAll();
        expect(toggle.lastBulk.value).toBeNull();
        expect(announce).not.toHaveBeenCalled();
    });
});
