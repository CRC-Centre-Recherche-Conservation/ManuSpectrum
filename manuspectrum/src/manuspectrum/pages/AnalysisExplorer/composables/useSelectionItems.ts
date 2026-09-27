import { computed, ref, watch } from "vue";

import { useItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useItems.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { ComputedRef, Ref } from "vue";

import type { Item } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestStatus } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

export interface SelectionItems {
    /** Every item read so far, by key; an item that left the Selection stays, to come back without a request. */
    byKey: Ref<Map<string, Item>>;
    /** The keys the items API reported no longer visible. */
    missing: Ref<Set<string>>;
    /** Whether every key of the Selection is read or reported missing. */
    settled: ComputedRef<boolean>;
    status: Ref<RequestStatus>;
    retry: () => void;
}

/**
 * The items of the Selection. Items read once are kept, so an addition asks
 * the items API for the new keys only (through the tab memo of `useItems`).
 */
export function useSelectionItems(): SelectionItems {
    const store = useExplorerStore();
    const byKey = ref(new Map<string, Item>());
    const missing = ref(new Set<string>());

    const items = useItems(() =>
        store.basket
            .map((item) => item.key)
            .filter((key) => !byKey.value.has(key) && !missing.value.has(key)),
    );

    const settled = computed(() =>
        store.basket.every(
            (item) => byKey.value.has(item.key) || missing.value.has(item.key),
        ),
    );

    watch(
        () => items.data.value,
        (answer) => {
            if (!answer) return;
            const read = new Map(byKey.value);
            for (const item of answer.items) read.set(item.key, item);
            byKey.value = read;
            missing.value = new Set([...missing.value, ...answer.missing]);
        },
        { immediate: true },
    );

    return {
        byKey,
        missing,
        settled,
        status: items.status,
        retry: items.retry,
    };
}
