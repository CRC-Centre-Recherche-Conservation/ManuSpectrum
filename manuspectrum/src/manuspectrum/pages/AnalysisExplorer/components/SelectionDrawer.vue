<script setup lang="ts">
import { computed, nextTick, ref, useTemplateRef, watch } from "vue";
import { useMediaQuery } from "@vueuse/core";
import Drawer from "primevue/drawer";
import { useGettext } from "vue3-gettext";

import SelectionPanel from "@/manuspectrum/pages/AnalysisExplorer/components/SelectionPanel.vue";

import { BASKET_LIMIT } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

const PHONE_QUERY = "(max-width: 30rem)";

/**
 * The Selection's own entry, on every Corpus screen: a button with the
 * number of items that opens the Selection in a drawer on the right (from
 * the bottom on a phone). Closing it (Escape, its close button) gives the
 * focus back to the button.
 */
const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const phone = useMediaQuery(PHONE_QUERY);
const button = useTemplateRef<HTMLButtonElement>("button");

const open = ref(false);

const label = computed(() =>
    interpolate(
        $gettext("Selection %{n}/%{limit}"),
        { n: store.basket.length, limit: BASKET_LIMIT },
        true,
    ),
);

watch(open, async (isOpen, wasOpen) => {
    if (isOpen || !wasOpen) return;
    await nextTick();
    button.value?.focus();
});

function show(): void {
    open.value = true;
}
</script>

<template>
    <div class="selection-drawer">
        <button
            ref="button"
            type="button"
            class="opener"
            aria-haspopup="dialog"
            :aria-label="label"
            :aria-expanded="open ? 'true' : 'false'"
            @click="show"
        >
            <span>{{ $gettext("Selection") }}</span>
            <span
                class="badge"
                aria-hidden="true"
                >{{ store.basket.length }}</span
            >
        </button>
        <Drawer
            v-model:visible="open"
            class="explorer-selection-drawer"
            :position="phone ? 'bottom' : 'right'"
            :pt="{
                root: {
                    role: 'dialog',
                    'aria-labelledby': 'selection-title',
                },
            }"
        >
            <SelectionPanel />
        </Drawer>
    </div>
</template>

<style scoped>
.selection-drawer .opener {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.875rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
}

.selection-drawer .opener:hover {
    border-color: var(--blue-text);
}

.selection-drawer .opener:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.selection-drawer .badge {
    display: inline-grid;
    place-items: center;
    min-inline-size: 1.25rem;
    block-size: 1.25rem;
    padding-inline: 0.375rem;
    border-radius: 999rem;
    background: var(--ink);
    color: var(--surface);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
}
</style>
