<script setup lang="ts">
import { useGettext } from "vue3-gettext";

import { useActiveFilters } from "@/manuspectrum/pages/AnalysisExplorer/composables/useActiveFilters.ts";

const { $gettext, interpolate } = useGettext();
const { activeFilters, clearAll } = useActiveFilters();

function removeLabel(label: string): string {
    return interpolate($gettext("Remove filter: %{label}"), { label }, true);
}
</script>

<template>
    <section
        v-if="activeFilters.length > 0"
        class="active-filters"
        :aria-label="$gettext('Active filters')"
    >
        <ul class="list">
            <li
                v-for="filter in activeFilters"
                :key="filter.id"
            >
                <button
                    type="button"
                    class="chip"
                    :aria-label="removeLabel(filter.label)"
                    @click="filter.clear"
                >
                    <span>{{ filter.label }}</span>
                    <span aria-hidden="true">×</span>
                </button>
            </li>
        </ul>
        <button
            type="button"
            class="clear-all"
            @click="clearAll"
        >
            <span>{{ $gettext("Clear all") }}</span>
        </button>
    </section>
</template>

<style scoped>
.active-filters {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    padding-block: 0.75rem;
}

.active-filters .list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    list-style: none;
}

.active-filters .chip,
.active-filters .clear-all {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: 2.75rem;
    padding-inline: 0.875rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.875rem;
    cursor: pointer;
}

.active-filters .clear-all {
    border-color: transparent;
    background: transparent;
    color: var(--blue-text);
    text-decoration: underline;
}

.active-filters .chip:focus-visible,
.active-filters .clear-all:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
