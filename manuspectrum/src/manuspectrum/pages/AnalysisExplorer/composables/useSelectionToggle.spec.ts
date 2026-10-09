import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, ref, watch } from "vue";

import { useSelectionToggle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionToggle.ts";
import {
    ANNOUNCE_KEY,
    SELECTION_HINTS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    analysisKey,
    characterizationKey,
    fileKey,
} from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
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

function material(n: number): string {
    return characterizationKey(uuid(500 + n));
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
            "Selection full (30 / 30)",
        );
    });

    it("counts the keys it holds", () => {
        toggle.toggle(key(1));
        toggle.toggle(key(2));
        expect(toggle.heldCount([key(1), key(2), key(3)])).toBe(2);
        expect(toggle.heldCount([])).toBe(0);
    });

    it("tells why a group is refused: full, or not enough room", () => {
        toggle.toggleAll(Array.from({ length: 27 }, (_, n) => key(n + 1)));
        expect(toggle.refusal([key(100), key(101)])).toBeNull();
        expect(
            toggle.refusal(Array.from({ length: 4 }, (_, n) => key(n + 100))),
        ).toEqual({
            kind: "room",
            needed: 4,
            free: 3,
        });
        toggle.toggleAll([key(50), key(51), key(52)]);
        expect(toggle.refusal([key(100)])).toEqual({ kind: "full" });
        expect(toggle.refusal([key(1), key(2)])).toBeNull();
    });

    it("announces a refused action once and nothing for an action that fits", () => {
        toggle.toggleAll(Array.from({ length: 28 }, (_, n) => key(n + 1)));
        toggle.dismiss();
        announce.mockReset();
        toggle.announceRefused([key(100)]);
        expect(announce).not.toHaveBeenCalled();
        toggle.announceRefused([key(100), key(101), key(102)]);
        expect(announce).toHaveBeenCalledTimes(1);
        expect(announce).toHaveBeenLastCalledWith(
            "Not enough room: 3 to add, 2 places left. Nothing was added.",
        );
        toggle.toggleAll([key(100), key(101)]);
        announce.mockReset();
        toggle.announceRefused([key(103)]);
        expect(announce).toHaveBeenCalledWith(
            "Selection full (30 / 30): nothing was added.",
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

    describe("counts items by kind", () => {
        it("says analyses, identified materials or items in the announcements", () => {
            toggle.toggleAll([material(1), material(2)]);
            expect(announce).toHaveBeenLastCalledWith(
                "2 identified materials added (A1 to A2). Selection: 2 / 30.",
            );
            toggle.toggleAll([material(1), material(2)]);
            expect(announce).toHaveBeenLastCalledWith(
                "2 identified materials removed from the Selection.",
            );
            toggle.dismiss();
            toggle.toggleAll([key(1), material(3)]);
            expect(announce).toHaveBeenLastCalledWith(
                "2 items added (A1 to A2). Selection: 2 / 30.",
            );
            toggle.toggleAll([key(1), material(3)]);
            expect(announce).toHaveBeenLastCalledWith(
                "2 items removed from the Selection.",
            );
        });

        it("says one analysis, one identified material or one item", () => {
            toggle.toggleAll([material(1), key(1)]);
            toggle.dismiss();
            toggle.toggleAll([material(1)]);
            expect(announce).toHaveBeenLastCalledWith(
                "1 identified material removed from the Selection.",
            );
        });

        it("counts an analysis file as an item, never as an analysis", () => {
            const file = fileKey(uuid(7), uuid(8));
            toggle.toggleAll([key(1), file]);
            expect(announce).toHaveBeenLastCalledWith(
                "2 items added (A1 to A2). Selection: 2 / 30.",
            );
            toggle.toggleAll([file]);
            toggle.dismiss();
            toggle.toggleAll([file, fileKey(uuid(7), uuid(9))]);
            expect(announce).toHaveBeenLastCalledWith(
                "2 items added (A2 to A3). Selection: 3 / 30.",
            );
            toggle.toggleAll(Array.from({ length: 26 }, (_, n) => key(n + 20)));
            expect(
                toggle.blockedReason([key(100), fileKey(uuid(7), uuid(10))]),
            ).toBe("2 items to add, 1 place left");
        });

        it("names the kind in the blocked reason", () => {
            toggle.toggleAll(Array.from({ length: 29 }, (_, n) => key(n + 1)));
            expect(toggle.blockedReason([material(1), material(2)])).toBe(
                "2 identified materials to add, 1 place left",
            );
            expect(toggle.blockedReason([key(100), material(2)])).toBe(
                "2 items to add, 1 place left",
            );
        });

        it("reports what an undo could not restore", () => {
            const store = useExplorerStore();
            toggle.toggleAll([key(1), key(2), key(3)]);
            toggle.toggleAll([key(1), key(2), key(3)]);
            store.addManyToBasket(
                Array.from({ length: 29 }, (_, n) => key(n + 10)),
            );
            expect(store.basketFree).toBe(1);
            announce.mockReset();
            toggle.undo();
            expect(announce).toHaveBeenCalledTimes(1);
            expect(announce.mock.calls[0][0]).toContain(
                "2 items could not be restored (Selection full).",
            );
            expect(store.basket).toHaveLength(30);
        });

        it("says one item could not be restored", () => {
            const store = useExplorerStore();
            toggle.toggleAll([key(1), key(2)]);
            toggle.toggleAll([key(1), key(2)]);
            store.addManyToBasket(
                Array.from({ length: 29 }, (_, n) => key(n + 10)),
            );
            announce.mockReset();
            toggle.undo();
            expect(announce.mock.calls[0][0]).toContain(
                "1 item could not be restored (Selection full).",
            );
        });
    });
});
