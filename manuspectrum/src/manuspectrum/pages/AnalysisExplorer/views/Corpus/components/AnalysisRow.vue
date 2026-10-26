<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import SelectionCheckbox from "@/manuspectrum/pages/AnalysisExplorer/components/SelectionCheckbox.vue";
import TechniqueTag from "@/manuspectrum/pages/AnalysisExplorer/components/TechniqueTag.vue";

import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";

import { analysisKey } from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { useSelectionToggle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionToggle.ts";

import type { AnalysisHit } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * One analysis of the results, headed by its name; technique, document,
 * component, date and data kinds as meta. Its Selection checkbox sits in a
 * column on the left; the title stays a separate button that opens the
 * analysis. A held analysis tints the row.
 */
const props = defineProps<{ hit: AnalysisHit }>();
const emit = defineEmits<{ open: [hit: AnalysisHit] }>();

const { $gettext, interpolate } = useGettext();
const { dataKindBadge } = useVocabulary();

const toggle = useSelectionToggle();
const key = computed(() => analysisKey(props.hit.id));
const held = computed(() => toggle.isHeld(key.value));
const hint = computed(() => ({
    title: props.hit.name,
    kind: $gettext("analysis"),
}));
const addLabel = computed(() =>
    interpolate(
        $gettext("Add %{name} to the Selection"),
        { name: props.hit.name.value },
        true,
    ),
);
const removeLabel = computed(() =>
    interpolate(
        $gettext("Remove %{name} from the Selection"),
        { name: props.hit.name.value },
        true,
    ),
);

function open(): void {
    emit("open", props.hit);
}
</script>

<template>
    <article
        class="analysis-row"
        :class="{ held: held }"
    >
        <SelectionCheckbox
            class="check"
            :item-key="key"
            :label="addLabel"
            :held-label="removeLabel"
            :hint="hint"
        />
        <h3 class="title">
            <button
                type="button"
                class="link"
                :lang="props.hit.name.lang || undefined"
                @click="open"
            >
                <span>{{ props.hit.name.value }}</span>
            </button>
        </h3>
        <p
            v-if="props.hit.technique"
            class="meta"
        >
            <TechniqueTag
                :code="props.hit.technique.code"
                :colour="props.hit.technique.colour"
                :label="props.hit.technique.label"
            />
        </p>
        <p class="where">
            <span :lang="props.hit.document.name.lang">{{
                props.hit.document.name.value
            }}</span>
            <span
                v-if="props.hit.component"
                :lang="props.hit.component.name.lang"
                >{{ props.hit.component.name.value }}</span
            >
            <span v-if="props.hit.date">{{ props.hit.date }}</span>
        </p>
        <ul class="badges">
            <li
                v-for="kind in props.hit.dataKinds"
                :key="kind"
                class="badge"
            >
                <span>{{ dataKindBadge(kind) }}</span>
            </li>
            <li
                v-if="props.hit.unpublished"
                class="badge draft"
            >
                <span>{{ $gettext("Draft") }}</span>
            </li>
        </ul>
    </article>
</template>

<style scoped>
.analysis-row {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    column-gap: 0.5rem;
    row-gap: 0.25rem;
    align-items: start;
    padding-block: 0.75rem;
    border-block-end: 0.0625rem solid var(--border);
}

.analysis-row.held {
    background: var(--selection-tint);
}

.analysis-row > .check {
    grid-column: 1;
    grid-row: 1 / span 4;
}

.analysis-row > :not(.check) {
    grid-column: 2;
}

.analysis-row .link {
    min-block-size: 2.75rem;
    border: none;
    background: transparent;
    color: var(--ink);
    font: inherit;
    font-size: 1.0625rem;
    font-weight: 600;
    text-align: start;
    overflow-wrap: anywhere;
    cursor: pointer;
}

.analysis-row .link:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.analysis-row .where {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    color: var(--ink-muted);
    font-size: 0.875rem;
}

.analysis-row .badges {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
    list-style: none;
}

.analysis-row .badge {
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    font-size: 0.75rem;
}

.analysis-row .badge.draft {
    border-color: var(--accent-text);
    color: var(--accent-text);
}

.analysis-row .meta {
    font-size: 0.875rem;
}
</style>
