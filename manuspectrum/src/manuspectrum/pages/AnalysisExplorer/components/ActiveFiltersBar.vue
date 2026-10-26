<script setup lang="ts">
import { computed, inject, ref } from "vue";
import { useGettext } from "vue3-gettext";

import { useActiveFilters } from "@/manuspectrum/pages/AnalysisExplorer/composables/useActiveFilters.ts";
import { CORPUS_COUNT_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

const { $gettext, $ngettext, interpolate } = useGettext();
const { activeFilters, clearAll } = useActiveFilters();
const corpusCount = inject(
    CORPUS_COUNT_KEY,
    () => ref<number | null>(null),
    true,
);

/** « See the whole corpus », with its number of documents once the home has told it. */
const clearLabel = computed(() => {
    const count = corpusCount.value;
    if (count === null) return $gettext("See the whole corpus");
    return interpolate(
        $ngettext(
            "See the whole corpus (%{n} document)",
            "See the whole corpus (%{n} documents)",
            count,
        ),
        { n: count },
        true,
    );
});

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
            <span>{{ clearLabel }}</span>
        </button>
    </section>
</template>

<style scoped>
.active-filters {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.375rem;
    padding-block: 0.25rem;
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
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
}

.active-filters .clear-all {
    border-color: var(--blue-text);
    background: var(--surface);
    color: var(--blue-text);
    font-weight: 600;
}

.active-filters .chip:focus-visible,
.active-filters .clear-all:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
