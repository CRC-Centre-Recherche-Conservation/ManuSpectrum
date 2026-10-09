<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useGettext } from "vue3-gettext";

import CollapsibleSection from "@/manuspectrum/pages/AnalysisExplorer/components/CollapsibleSection.vue";

import { foldText } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";

import type { PlaceSummary } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/place-symbols.ts";

/**
 * The text equivalent of the map: one button per mapped place, by folded
 * name, named « Paris — 9 documents, 14 Composants »; an attributed place
 * (an area, or reached through its parent) is in italics. The selected one
 * is `aria-current`. Under the list, the events without a mapped place
 * open their own panel. Folds into « Places (n) » with its counts; `open`
 * sets the fold, the reader may change it.
 */
const props = withDefaults(
    defineProps<{
        summaries: PlaceSummary[];
        unplaced: number;
        selected: string | null;
        open?: boolean;
    }>(),
    { open: true },
);
const emit = defineEmits<{
    select: [id: string];
    hover: [id: string | null];
    unplaced: [];
}>();

const { $gettext, $ngettext, interpolate } = useGettext();

const unfolded = ref(props.open);

const sorted = computed(() =>
    [...props.summaries].sort((a, b) =>
        foldText(a.name.value).localeCompare(foldText(b.name.value)),
    ),
);
const title = computed(() =>
    interpolate($gettext("Places (%{n})"), { n: props.summaries.length }, true),
);
const summaryText = computed(() =>
    interpolate(
        $ngettext(
            "%{n} place · %{m} without a mapped place",
            "%{n} places · %{m} without a mapped place",
            props.summaries.length,
        ),
        { n: props.summaries.length, m: props.unplaced },
        true,
    ),
);
const unplacedText = computed(() =>
    interpolate(
        $ngettext(
            "%{n} event without a mapped place",
            "%{n} events without a mapped place",
            props.unplaced,
        ),
        { n: props.unplaced },
        true,
    ),
);

watch(
    () => props.open,
    (open) => {
        unfolded.value = open;
    },
);

function nameOf(summary: PlaceSummary): string {
    const documents = summary.documents.size;
    const components = summary.components.size;
    return interpolate(
        $gettext("%{place} — %{documents}, %{components}"),
        {
            place: summary.name.value,
            documents: interpolate(
                $ngettext("%{n} document", "%{n} documents", documents),
                { n: documents },
                true,
            ),
            components: interpolate(
                $ngettext("%{n} Composant", "%{n} Composants", components),
                { n: components },
                true,
            ),
        },
        true,
    );
}
</script>

<template>
    <CollapsibleSection
        class="place-list"
        :title="title"
        :open="unfolded"
        :summary="summaryText"
        @toggle="unfolded = $event"
    >
        <ul class="places">
            <li
                v-for="summary in sorted"
                :key="summary.id"
            >
                <button
                    type="button"
                    class="place"
                    :class="{ attributed: summary.dashed }"
                    :data-place="summary.id"
                    :aria-label="nameOf(summary)"
                    :aria-current="
                        props.selected === summary.id ? 'true' : undefined
                    "
                    @click="emit('select', summary.id)"
                    @mouseenter="emit('hover', summary.id)"
                    @mouseleave="emit('hover', null)"
                    @focus="emit('hover', summary.id)"
                    @blur="emit('hover', null)"
                >
                    <span
                        class="name"
                        :lang="summary.name.lang || undefined"
                        :title="summary.name.value"
                        >{{ summary.name.value }}</span
                    >
                    <span
                        v-if="summary.unpublished"
                        class="unpublished"
                        aria-hidden="true"
                        >{{ $gettext("unpublished") }}</span
                    >
                    <span
                        class="counts"
                        aria-hidden="true"
                        >{{
                            `${summary.documents.size} · ${summary.components.size}`
                        }}</span
                    >
                </button>
            </li>
        </ul>
        <button
            v-if="props.unplaced > 0"
            type="button"
            class="more"
            @click="emit('unplaced')"
        >
            <span>{{ unplacedText }}</span>
        </button>
    </CollapsibleSection>
</template>

<style scoped>
.place-list .places {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    margin: 0;
    padding: 0;
    list-style: none;
}

/* OnThisPage row button */
.place-list .place {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    inline-size: 100%;
    min-inline-size: 0;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: none;
    border-inline-start: 0.1875rem solid transparent;
    border-radius: 0.25rem;
    background: none;
    color: var(--ink);
    font: inherit;
    font-size: 0.8125rem;
    text-align: start;
    cursor: pointer;
}

.place-list .place:hover {
    background: var(--bg-alt);
}

.place-list .place[aria-current="true"] {
    border-inline-start-color: var(--blue-text);
    background: var(--bg-alt);
    font-weight: 600;
}

.place-list .name {
    flex: 1 1 auto;
    min-inline-size: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.place-list .place.attributed .name {
    font-style: italic;
}

/* FacetValues .unpublished */
.place-list .unpublished {
    flex: none;
    padding-inline: 0.375rem;
    border: 0.0625rem solid var(--accent-text);
    border-radius: 999rem;
    color: var(--accent-text);
    font-size: 0.6875rem;
    font-weight: 400;
}

.place-list .counts {
    flex: none;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-variant-numeric: tabular-nums;
    font-weight: 400;
}

/* FacetRail .more */
.place-list .more {
    justify-self: start;
    min-block-size: var(--explorer-target, 2.75rem);
    padding: 0;
    border: none;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
}

.place-list .more:hover {
    text-decoration: underline;
}

.place-list .place:focus-visible,
.place-list .more:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

@media (forced-colors: active) {
    .place-list .place[aria-current="true"] {
        outline: 0.125rem solid Highlight;
    }
}
</style>
