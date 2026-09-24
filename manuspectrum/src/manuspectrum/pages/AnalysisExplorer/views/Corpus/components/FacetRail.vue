<script setup lang="ts">
import { ref } from "vue";
import { useGettext } from "vue3-gettext";

import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";

import type {
    Facet,
    FacetKey,
    FacetValue,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const PREVIEW_SIZE = 6;

const props = defineProps<{ facets: Facet[] }>();
const emit = defineEmits<{ change: [key: FacetKey, ids: string[]] }>();

const { $gettext, interpolate } = useGettext();
const { facetTitle } = useVocabulary();

const expanded = ref<Set<FacetKey>>(new Set());

function isExpanded(key: FacetKey): boolean {
    return expanded.value.has(key);
}

function toggleExpanded(key: FacetKey): void {
    const next = new Set(expanded.value);
    if (next.has(key)) {
        next.delete(key);
    } else {
        next.add(key);
    }
    expanded.value = next;
}

function visibleValues(facet: Facet): FacetValue[] {
    if (isExpanded(facet.key)) {
        return facet.values;
    }
    return facet.values.filter(
        (value, index) => index < PREVIEW_SIZE || value.selected,
    );
}

function moreLabel(facet: Facet): string {
    return isExpanded(facet.key)
        ? $gettext("Show fewer")
        : interpolate(
              $gettext("Show all (%{count})"),
              {
                  count: facet.values.length,
              },
              true,
          );
}

function onChange(facet: Facet, id: string, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    const ids = facet.values
        .filter((value) => (value.id === id ? checked : value.selected))
        .map((value) => value.id);
    emit("change", facet.key, ids);
}
</script>

<template>
    <div class="facet-rail">
        <fieldset
            v-for="facet in props.facets"
            :key="facet.key"
            class="facet"
        >
            <legend class="title">
                <span>{{ facetTitle(facet.key) }}</span>
            </legend>
            <p class="hint">
                <span>{{ $gettext("at least one of") }}</span>
            </p>
            <ul class="values">
                <li
                    v-for="value in visibleValues(facet)"
                    :key="value.id"
                >
                    <label class="value">
                        <input
                            type="checkbox"
                            :checked="value.selected"
                            :disabled="value.count === 0 && !value.selected"
                            @change="onChange(facet, value.id, $event)"
                        />
                        <span
                            class="label"
                            :lang="value.label.lang"
                            >{{ value.label.value }}</span
                        >
                        <span class="count">{{ value.count }}</span>
                    </label>
                </li>
            </ul>
            <button
                v-if="facet.values.length > PREVIEW_SIZE"
                type="button"
                class="more"
                :aria-expanded="isExpanded(facet.key) ? 'true' : 'false'"
                @click="toggleExpanded(facet.key)"
            >
                <span>{{ moreLabel(facet) }}</span>
            </button>
        </fieldset>
    </div>
</template>

<style scoped>
.facet-rail {
    display: grid;
    gap: 1.25rem;
}

.facet-rail .facet {
    display: grid;
    gap: 0.375rem;
    border: none;
}

.facet-rail .title {
    font-weight: 600;
    color: var(--ink);
}

.facet-rail .hint {
    color: var(--ink-muted);
    font-size: 0.75rem;
}

.facet-rail .values {
    display: grid;
    gap: 0.125rem;
    list-style: none;
}

.facet-rail .value {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 0.5rem;
    min-block-size: 2.75rem;
    cursor: pointer;
}

.facet-rail .count {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.75rem;
}

.facet-rail .more {
    justify-self: start;
    min-block-size: 2.75rem;
    border: none;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    text-decoration: underline;
    cursor: pointer;
}

.facet-rail input:focus-visible,
.facet-rail .more:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
