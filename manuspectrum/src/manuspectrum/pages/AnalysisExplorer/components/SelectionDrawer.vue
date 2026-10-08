<script setup lang="ts">
import { computed, nextTick, ref, useTemplateRef, watch } from "vue";
import { useMediaQuery } from "@vueuse/core";
import Drawer from "primevue/drawer";
import { useGettext } from "vue3-gettext";

import SelectionPanel from "@/manuspectrum/pages/AnalysisExplorer/components/SelectionPanel.vue";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";

import { BASKET_LIMIT } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

const PHONE_QUERY = "(max-width: 30rem)";

/**
 * The Selection's own entry, on every Corpus screen, and its only capacity
 * gauge: a button with « n/30 », that opens the Selection in a drawer on the
 * right (from the bottom on a phone). Full, the border and the chip turn
 * ochre and an icon appears. State is in the accessible name, not in the
 * colour. `open()` is exposed for the notices (`SELECTION_DRAWER_KEY`).
 * Closing it (Escape, its close button) gives the focus back to the element
 * that opened it if it is still on the page, else to the button; « Compare »
 * closes it and leaves the focus to the Compare view.
 */
const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const phone = useMediaQuery(PHONE_QUERY);
const button = useTemplateRef<HTMLButtonElement>("button");

const open = ref(false);
/** Closed by « Compare »: the focus goes to the Compare view, not back to the button. */
const leftForCompare = ref(false);
/** What opened the drawer, when it was not the button. */
let opener: Element | null = null;

const held = computed(() => store.basket.length);
const full = computed(() => held.value >= BASKET_LIMIT);
const label = computed(() =>
    interpolate(
        full.value
            ? $gettext("Selection full: %{limit} of %{limit}")
            : $gettext("Selection: %{n} of %{limit}"),
        { n: held.value, limit: BASKET_LIMIT },
        true,
    ),
);

watch(open, async (isOpen, wasOpen) => {
    if (isOpen || !wasOpen) return;
    if (leftForCompare.value) {
        leftForCompare.value = false;
        return;
    }
    await nextTick();
    const target = opener?.isConnected ? opener : button.value;
    opener = null;
    (target as HTMLElement | null)?.focus();
});

function show(): void {
    open.value = true;
}

function openFrom(from?: Element | null): void {
    opener = from && from !== button.value ? from : null;
    open.value = true;
}

defineExpose({ open: openFrom });

function closeForCompare(): void {
    leftForCompare.value = true;
    open.value = false;
}
</script>

<template>
    <div class="selection-drawer">
        <button
            ref="button"
            type="button"
            class="opener"
            :class="{ full: full }"
            aria-haspopup="dialog"
            :aria-label="label"
            :aria-expanded="open ? 'true' : 'false'"
            @click="show"
        >
            <svg
                v-if="full"
                class="icon"
                :viewBox="ICON_VIEW_BOX"
                aria-hidden="true"
                focusable="false"
            >
                <path
                    v-for="shape in ICONS['exclamation-circle']"
                    :key="shape"
                    :d="shape"
                />
            </svg>
            <span>{{ $gettext("Selection") }}</span>
            <span
                class="badge"
                aria-hidden="true"
                >{{ held }}<span class="of">/{{ BASKET_LIMIT }}</span></span
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
            <SelectionPanel @compare="closeForCompare" />
        </Drawer>
    </div>
</template>

<style scoped>
.selection-drawer .opener {
    position: relative;
    display: inline-flex;
    overflow: hidden;
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

.selection-drawer .opener.full {
    border-color: var(--accent);
}

.selection-drawer .icon {
    inline-size: 1rem;
    block-size: 1rem;
    fill: var(--accent-text);
}

.selection-drawer .opener.full .badge {
    background: var(--accent-text);
    color: var(--surface);
}

.selection-drawer .badge .of {
    opacity: 0.7;
}

.selection-drawer .badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
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
