<script setup lang="ts">
import { computed, inject } from "vue";
import { useGettext } from "vue3-gettext";

import { SCREEN_FOCUS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { BASKET_LIMIT } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { isViewAvailable } from "@/manuspectrum/pages/AnalysisExplorer/views/registry.ts";

import type { BulkStatus } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const UNDO_EVENT = "undo" as const;
const COMPARE_EVENT = "compare" as const;
const DISMISS_EVENT = "dismiss" as const;

/**
 * The line that stays under a grouped change of the Selection until it is
 * dismissed: what changed and the new size, then « Undo » and « Compare »
 * (opens Compare and asks its heading for the focus) and « × ». The change is
 * spoken once by the shell's live region, so the line is a `status` that
 * does not announce itself again.
 */
const props = defineProps<{ status: BulkStatus | null }>();

const emit = defineEmits<{
    (event: typeof UNDO_EVENT): void;
    (event: typeof COMPARE_EVENT): void;
    (event: typeof DISMISS_EVENT): void;
}>();

const screenFocus = inject(SCREEN_FOCUS_KEY, null);

const store = useExplorerStore();
const { $gettext, $ngettext, interpolate } = useGettext();

const canCompare = computed(() => isViewAvailable("compare"));
const message = computed(() => {
    const status = props.status;
    if (status === null) return "";
    const count = status.keys.length;
    if (status.kind === "removed") {
        return interpolate(
            $ngettext(
                "%{n} analysis removed from the Selection.",
                "%{n} analyses removed from the Selection.",
                count,
            ),
            { n: count },
            true,
        );
    }
    return interpolate(
        $ngettext(
            "%{n} analysis added (%{first}). Selection: %{held} / %{limit}.",
            "%{n} analyses added (%{first} to %{last}). Selection: %{held} / %{limit}.",
            count,
        ),
        {
            n: count,
            first: status.slots[0],
            last: status.slots[status.slots.length - 1],
            held: status.total,
            limit: BASKET_LIMIT,
        },
        true,
    );
});

function compare(): void {
    if (screenFocus) screenFocus.value = true;
    store.setView("compare");
    emit(COMPARE_EVENT);
}
</script>

<template>
    <div
        v-if="props.status"
        class="bulk-status-line"
        role="status"
        aria-live="off"
    >
        <p class="message">
            <span>{{ message }}</span>
        </p>
        <button
            type="button"
            data-action="undo"
            @click="emit(UNDO_EVENT)"
        >
            <span>{{ $gettext("Undo") }}</span>
        </button>
        <button
            v-if="canCompare"
            type="button"
            data-action="compare"
            @click="compare"
        >
            <span>{{ $gettext("Compare") }}</span>
        </button>
        <button
            type="button"
            data-action="dismiss"
            :aria-label="$gettext('Dismiss')"
            @click="emit(DISMISS_EVENT)"
        >
            <span aria-hidden="true">×</span>
        </button>
    </div>
</template>

<style scoped>
.bulk-status-line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    padding-inline: 0.75rem;
    border-inline-start: 0.1875rem solid var(--blue-text);
    border-radius: 0.25rem;
    background: var(--selection-tint);
    color: var(--ink);
    font-size: 0.875rem;
}

.bulk-status-line .message {
    flex: 1 1 auto;
}

.bulk-status-line button {
    min-block-size: var(--explorer-target, 2.75rem);
    min-inline-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
}

.bulk-status-line button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: -0.125rem;
}
</style>
