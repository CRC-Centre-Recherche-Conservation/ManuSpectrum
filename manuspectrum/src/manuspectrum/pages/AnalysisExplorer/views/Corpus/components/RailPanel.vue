<script setup lang="ts">
import { computed, nextTick, ref, useTemplateRef, watch } from "vue";
import { useMediaQuery } from "@vueuse/core";
import Drawer from "primevue/drawer";
import { useGettext } from "vue3-gettext";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

const COMPACT_QUERY = "(max-width: 80rem)";
const FOCUSABLE = "input:not([disabled]), button:not([disabled])";

/**
 * The filter column of a Corpus screen. Below 80rem it folds into a toggle
 * that opens the filters in a left drawer; the drawer closes on Escape or on
 * `showLabel` (« See n analyses »), and the focus goes back to the toggle.
 */
const props = withDefaults(
    defineProps<{
        showLabel: string;
        /** The heading of the filters; « Filters » by default. */
        title?: string;
    }>(),
    { title: "" },
);
defineExpose({ focusFilters });

const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const compact = useMediaQuery(COMPACT_QUERY);
const toggle = useTemplateRef<HTMLButtonElement>("toggle");
const column = useTemplateRef<HTMLElement>("column");

const open = ref(false);

const heading = computed(() => props.title || $gettext("Filters"));
const toggleLabel = computed(() =>
    interpolate(
        $gettext("Filters (%{count})"),
        { count: store.activeFilterCount },
        true,
    ),
);

watch(open, async (isOpen, wasOpen) => {
    if (isOpen || !wasOpen) return;
    await nextTick();
    toggle.value?.focus();
});

function openDrawer(): void {
    open.value = true;
}

function closeDrawer(): void {
    open.value = false;
}

/** Opens the drawer below 80rem; otherwise puts the focus on the first filter. */
function focusFilters(): void {
    if (compact.value) {
        openDrawer();
        return;
    }
    const first = column.value?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? column.value)?.focus();
}
</script>

<template>
    <div
        v-if="compact"
        class="rail-panel is-compact"
    >
        <button
            ref="toggle"
            type="button"
            class="toggle"
            aria-haspopup="dialog"
            :aria-expanded="open ? 'true' : 'false'"
            @click="openDrawer"
        >
            <span>{{ toggleLabel }}</span>
        </button>
        <Drawer
            v-model:visible="open"
            class="explorer-rail-drawer"
            position="left"
            :header="heading"
            :pt="{
                root: { role: 'dialog', 'aria-label': heading },
            }"
        >
            <div class="rail-panel-body">
                <slot></slot>
                <button
                    type="button"
                    class="show"
                    @click="closeDrawer"
                >
                    <span>{{ props.showLabel }}</span>
                </button>
            </div>
        </Drawer>
    </div>
    <aside
        v-else
        ref="column"
        class="rail-panel"
        tabindex="-1"
        :aria-label="heading"
    >
        <h2 class="rail-title">
            <span>{{ heading }}</span>
        </h2>
        <slot></slot>
    </aside>
</template>

<style scoped>
.rail-panel {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    align-content: start;
    gap: 1rem;
    min-inline-size: 0;
}

.rail-panel:not(.is-compact) {
    padding: 1rem;
    border: 0.0625rem solid var(--border);
    border-radius: var(--explorer-radius, 0.625rem);
    background: var(--surface);
}

.rail-panel:focus-visible,
.rail-panel .toggle:focus-visible,
.rail-panel-body .show:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.rail-panel .toggle {
    justify-self: start;
    display: inline-flex;
    align-items: center;
    min-block-size: var(--explorer-target);
    padding-inline: 0.875rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.rail-panel .rail-title {
    font-family: var(--font-display);
    font-size: 1.0625rem;
    font-weight: 500;
}

.rail-panel-body {
    display: grid;
    gap: 1rem;
}

.rail-panel-body .show {
    position: sticky;
    inset-block-end: 0;
    min-block-size: 2.75rem;
    border: none;
    border-radius: 0.5rem;
    background: var(--ink);
    color: var(--surface);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
}
</style>
