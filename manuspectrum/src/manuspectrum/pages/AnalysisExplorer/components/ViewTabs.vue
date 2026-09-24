<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { availableViews } from "@/manuspectrum/pages/AnalysisExplorer/views/registry.ts";

import type { ExplorerView } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const { viewTitle } = useVocabulary();

const views = computed(() => availableViews());

function tabLabel(view: ExplorerView): string {
    if (view === "compare") {
        return interpolate($gettext("Compare (%{count})"), {
            count: store.basket.length,
        });
    }
    return viewTitle(view);
}

function select(view: ExplorerView): void {
    store.setView(view);
}
</script>

<template>
    <nav
        v-if="views.length > 1"
        class="view-tabs"
        :aria-label="$gettext('Explorer views')"
    >
        <ul class="list">
            <li
                v-for="view in views"
                :key="view"
            >
                <button
                    type="button"
                    class="tab"
                    :aria-current="store.view === view ? 'page' : undefined"
                    @click="select(view)"
                >
                    <span>{{ tabLabel(view) }}</span>
                </button>
            </li>
        </ul>
    </nav>
</template>

<style scoped>
.view-tabs .list {
    display: flex;
    gap: 0.25rem;
    list-style: none;
    border-block-end: 0.0625rem solid var(--border-hover);
}

.view-tabs .tab {
    min-block-size: 2.75rem;
    padding-inline: 1rem;
    border: none;
    border-block-end: 0.1875rem solid transparent;
    background: transparent;
    color: var(--ink-muted);
    font: inherit;
    cursor: pointer;
}

.view-tabs .tab[aria-current="page"] {
    border-block-end-color: var(--ink);
    color: var(--ink);
    font-weight: 600;
}

.view-tabs .tab:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
