<script setup lang="ts">
import { useId } from "vue";
import { useGettext } from "vue3-gettext";

import { techniqueClass } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

export interface LegendEntry {
    key: string;
    code: string;
    colour: number | null;
    label: Label;
    count: number;
}

/** The techniques drawn on the page, with the number of analyses of each; folds to its title, folded when the explorer opens (state in the store). */
const props = defineProps<{ entries: LegendEntry[] }>();

const store = useExplorerStore();
const { $gettext } = useGettext();
const listId = useId();

function toggle(): void {
    store.setLegendOpen(!store.legendOpen);
}
</script>

<template>
    <div
        v-if="props.entries.length > 0"
        class="folio-legend"
    >
        <button
            type="button"
            class="toggle"
            :aria-controls="listId"
            :aria-expanded="store.legendOpen ? 'true' : 'false'"
            @click="toggle"
        >
            <span>{{ $gettext("Techniques on this page") }}</span>
            <span
                class="chevron"
                aria-hidden="true"
                >{{ store.legendOpen ? "▾" : "▸" }}</span
            >
        </button>
        <ul
            v-show="store.legendOpen"
            :id="listId"
            class="entries"
        >
            <li
                v-for="entry in props.entries"
                :key="entry.key"
            >
                <span
                    class="code"
                    aria-hidden="true"
                    :class="techniqueClass('code', entry.colour)"
                >
                    {{ entry.code }}
                </span>
                <span
                    class="name"
                    :lang="entry.label.lang || undefined"
                    >{{ entry.label.value }}</span
                >
                <span class="count">{{ entry.count }}</span>
            </li>
        </ul>
    </div>
</template>

<style scoped>
.folio-legend {
    display: grid;
    justify-items: start;
    gap: 0.25rem;
    max-inline-size: min(22rem, 100%);
    padding: 0.375rem 0.5rem;
    border-radius: 0.5rem;
    background: color-mix(in srgb, var(--stage) 88%, transparent);
    color: var(--surface);
    font-size: 0.75rem;
}

.folio-legend .toggle {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-block-size: 1.5rem;
    padding: 0 0.25rem;
    border: none;
    background: transparent;
    color: inherit;
    font: inherit;
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
}

.folio-legend .toggle:focus-visible {
    outline: 0.125rem solid var(--surface);
    outline-offset: 0.125rem;
}

.folio-legend .entries {
    display: grid;
    gap: 0.25rem;
    padding: 0;
    list-style: none;
}

.folio-legend li {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 0.5rem;
}

.folio-legend .code {
    display: inline-grid;
    place-items: center;
    min-inline-size: 1.25rem;
    block-size: 1.25rem;
    padding-inline: 0.125rem;
    border: 0.0625rem solid var(--surface);
    border-radius: 999rem;
    background: var(--ink);
    color: var(--stage);
    font: 600 0.5625rem var(--font-body);
}

.folio-legend .code--tech-1 {
    background: var(--tech-1);
}

.folio-legend .code--tech-2 {
    background: var(--tech-2);
}

.folio-legend .code--tech-3 {
    background: var(--tech-3);
}

.folio-legend .code--tech-4 {
    background: var(--tech-4);
}

.folio-legend .code--tech-5 {
    background: var(--tech-5);
}

.folio-legend .code--tech-6 {
    background: var(--tech-6);
}

.folio-legend .code--tech-7 {
    background: var(--tech-7);
}

.folio-legend .code--tech-8 {
    background: var(--tech-8);
}

.folio-legend .code--tech-9 {
    background: var(--tech-9);
}

.folio-legend .code--tech-10 {
    background: var(--tech-10);
}

.folio-legend .code--ink {
    background: var(--surface);
    color: var(--ink);
}

.folio-legend .count {
    font-family: var(--font-mono);
    opacity: 0.8;
}
</style>
