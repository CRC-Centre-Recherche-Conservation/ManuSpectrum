import { inject, ref } from "vue";
import { useGettext } from "vue3-gettext";

import {
    ANNOUNCE_KEY,
    SELECTION_HINTS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    checkState,
    planToggleAll,
} from "@/manuspectrum/pages/AnalysisExplorer/selection/bulk.ts";
import {
    BASKET_LIMIT,
    slotLabel,
} from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { Ref } from "vue";
import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import type { CheckState } from "@/manuspectrum/pages/AnalysisExplorer/selection/bulk.ts";
import type {
    BasketItem,
    BulkStatus,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export interface SelectionToggle {
    isHeld: (key: string) => boolean;
    /** The slot label (« A3 ») of a held key, else null. */
    slotOf: (key: string) => string | null;
    toggle: (key: string, hint?: SelectionHint) => void;
    stateOf: (keys: readonly string[]) => CheckState;
    toggleAll: (
        keys: readonly string[],
        hints?: ReadonlyMap<string, SelectionHint> | null,
    ) => void;
    /** Why the keys cannot all be added (« 48 analyses to add, 26 places left »), else null. */
    blockedReason: (keys: readonly string[]) => string | null;
    /** Empties the Selection; `undo()` puts every item back at its slot. */
    clearAll: () => void;
    lastBulk: Ref<BulkStatus | null>;
    undo: () => void;
    dismiss: () => void;
}

// One Selection, so one last grouped change: the checkbox that makes it and
// the status line that undoes it are in different components.
const lastBulk = ref<BulkStatus | null>(null);
let removedItems: BasketItem[] = [];

/**
 * Reads and changes the Selection for the checkboxes: one key at a time or a
 * group, all or nothing. Each action is announced once through `ANNOUNCE_KEY`;
 * a grouped change leaves `lastBulk`, which `undo()` reverses (an addition is
 * removed, a removal is restored at its own slots). Hints are recorded before
 * the keys are added, so the Selection can name an item before it has read it.
 */
export function useSelectionToggle(): SelectionToggle {
    const store = useExplorerStore();
    const { $gettext, $ngettext, interpolate } = useGettext();
    const announce = inject(ANNOUNCE_KEY, () => undefined);
    const selectionHints = inject(
        SELECTION_HINTS_KEY,
        () => ref(new Map<string, SelectionHint>()),
        true,
    );

    function heldKeys(): Set<string> {
        return new Set(store.basket.map((item) => item.key));
    }

    function slotOf(key: string): string | null {
        const item = store.basket.find((entry) => entry.key === key);
        return item ? slotLabel(item.slot) : null;
    }

    function recordHints(
        incoming: ReadonlyMap<string, SelectionHint> | null | undefined,
    ): void {
        if (!incoming || incoming.size === 0) return;
        const next = new Map(selectionHints.value);
        for (const [key, hint] of incoming) next.set(key, hint);
        selectionHints.value = next;
    }

    function stateOf(keys: readonly string[]): CheckState {
        return checkState(keys, heldKeys());
    }

    function blockedReason(keys: readonly string[]): string | null {
        const plan = planToggleAll(keys, heldKeys(), store.basketFree);
        if (plan.action !== "refused") return null;
        return [
            interpolate(
                $ngettext(
                    "%{n} analysis to add",
                    "%{n} analyses to add",
                    plan.needed,
                ),
                { n: plan.needed },
                true,
            ),
            interpolate(
                $ngettext(
                    "%{free} place left",
                    "%{free} places left",
                    plan.free,
                ),
                { free: plan.free },
                true,
            ),
        ].join(", ");
    }

    function toggle(key: string, hint?: SelectionHint): void {
        if (heldKeys().has(key)) {
            store.removeFromBasket(key);
            announce(
                interpolate(
                    $gettext("Removed from the Selection (%{n}/%{limit})."),
                    { n: store.basket.length, limit: BASKET_LIMIT },
                    true,
                ),
            );
            return;
        }
        if (store.basketFree < 1) return;
        recordHints(hint ? new Map([[key, hint]]) : null);
        store.addToBasket(key);
        announce(
            interpolate(
                $gettext("Added to the Selection (%{n}/%{limit})."),
                { n: store.basket.length, limit: BASKET_LIMIT },
                true,
            ),
        );
    }

    function announceAdded(slots: readonly string[]): void {
        announce(
            interpolate(
                $ngettext(
                    "%{n} analysis added (%{first}). Selection: %{held} / %{limit}.",
                    "%{n} analyses added (%{first} to %{last}). Selection: %{held} / %{limit}.",
                    slots.length,
                ),
                {
                    n: slots.length,
                    first: slots[0],
                    last: slots[slots.length - 1],
                    held: store.basket.length,
                    limit: BASKET_LIMIT,
                },
                true,
            ),
        );
    }

    function announceRemoved(count: number): void {
        announce(
            interpolate(
                $ngettext(
                    "%{n} analysis removed from the Selection.",
                    "%{n} analyses removed from the Selection.",
                    count,
                ),
                { n: count },
                true,
            ),
        );
    }

    function toggleAll(
        keys: readonly string[],
        hints?: ReadonlyMap<string, SelectionHint> | null,
    ): void {
        const plan = planToggleAll(keys, heldKeys(), store.basketFree);
        if (plan.action === "refused" || plan.keys.length === 0) return;
        if (plan.action === "remove") {
            removedItems = store.removeManyFromBasket(plan.keys);
            lastBulk.value = {
                kind: "removed",
                keys: removedItems.map((item) => item.key),
                slots: removedItems.map((item) => slotLabel(item.slot)),
                total: store.basket.length,
            };
            announceRemoved(removedItems.length);
            return;
        }
        recordHints(hints);
        const result = store.addManyToBasket(plan.keys);
        if (result.refused !== null || result.added.length === 0) return;
        removedItems = [];
        const slots = result.added.map((key) => slotOf(key) ?? "");
        lastBulk.value = {
            kind: "added",
            keys: result.added,
            slots,
            total: store.basket.length,
        };
        announceAdded(slots);
    }

    function clearAll(): void {
        if (store.basket.length === 0) return;
        removedItems = store.removeManyFromBasket(
            store.basket.map((item) => item.key),
        );
        lastBulk.value = {
            kind: "emptied",
            keys: removedItems.map((item) => item.key),
            slots: removedItems.map((item) => slotLabel(item.slot)),
            total: 0,
        };
        announce(
            interpolate(
                $gettext("Selection emptied (%{n})."),
                { n: removedItems.length },
                true,
            ),
        );
    }

    function undo(): void {
        const status = lastBulk.value;
        if (status === null) return;
        lastBulk.value = null;
        if (status.kind === "added") {
            announceRemoved(store.removeManyFromBasket(status.keys).length);
            return;
        }
        const restored = store.restoreBasketItems(removedItems);
        removedItems = [];
        if (restored.kept.length > 0) {
            announceAdded(restored.kept.map((key) => slotOf(key) ?? ""));
        }
    }

    function dismiss(): void {
        lastBulk.value = null;
        removedItems = [];
    }

    return {
        isHeld: (key) => heldKeys().has(key),
        slotOf,
        toggle,
        stateOf,
        toggleAll,
        blockedReason,
        clearAll,
        lastBulk,
        undo,
        dismiss,
    };
}
