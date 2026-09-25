<script setup lang="ts">
import { computed, useId, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type {
    Label,
    SampleSummary,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** `headingId` names the heading (a drawer is labelled by it); `closable: false` hides « Close » where the container has its own. */
const props = withDefaults(
    defineProps<{
        sample: SampleSummary;
        analysisNames: Map<string, Label>;
        headingId?: string;
        closable?: boolean;
    }>(),
    { headingId: undefined, closable: true },
);

const emit = defineEmits<{ close: [] }>();
defineExpose({ focusHeading });

const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const sectionId = useId();
const heading = useTemplateRef<HTMLElement>("heading");

const analysesTitle = computed(() =>
    interpolate(
        $gettext("Analyses on this sample (%{n})"),
        { n: props.sample.analyses.length },
        true,
    ),
);

function analysisName(id: string, index: number): Label {
    return (
        props.analysisNames.get(id) ?? {
            value: interpolate(
                $gettext("Analysis %{n}"),
                { n: index + 1 },
                true,
            ),
            lang: "",
        }
    );
}

function openAnalysis(id: string): void {
    store.focusOn({ kind: "analysis", id });
}

function close(): void {
    emit("close");
}

function focusHeading(): void {
    heading.value?.focus();
}
</script>

<template>
    <article class="sample-card">
        <header class="card-head">
            <h3
                :id="props.headingId"
                ref="heading"
                class="name"
                tabindex="-1"
                :lang="props.sample.name.lang"
            >
                <span>{{ props.sample.name.value }}</span>
            </h3>
            <p class="meta">
                <span>{{ $gettext("Sample") }}</span>
                <span
                    v-if="props.sample.unpublished"
                    class="badge draft"
                >
                    {{ $gettext("Draft") }}
                </span>
            </p>
            <button
                v-if="props.closable"
                type="button"
                class="close"
                @click="close"
            >
                <span>{{ $gettext("Close") }}</span>
            </button>
        </header>

        <section
            class="analyses"
            :aria-labelledby="`${sectionId}-analyses`"
        >
            <h4 :id="`${sectionId}-analyses`">
                <span>{{ analysesTitle }}</span>
            </h4>
            <ul v-if="props.sample.analyses.length > 0">
                <li
                    v-for="(id, index) in props.sample.analyses"
                    :key="id"
                >
                    <button
                        type="button"
                        @click="openAnalysis(id)"
                    >
                        <span :lang="analysisName(id, index).lang || undefined">
                            {{ analysisName(id, index).value }}
                        </span>
                    </button>
                </li>
            </ul>
        </section>
    </article>
</template>

<style scoped>
.sample-card {
    display: grid;
    gap: 1rem;
}

.sample-card .card-head {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1rem;
    align-items: center;
}

.sample-card .card-head .name {
    flex: 1 1 100%;
    font-weight: 600;
}

.sample-card .card-head .close {
    margin-inline-start: auto;
}

.sample-card .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
    color: var(--ink-muted);
}

.sample-card .badge {
    padding: 0 0.375rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    font-size: 0.75rem;
}

.sample-card section {
    display: grid;
    gap: 0.5rem;
}

.sample-card h4 {
    font-weight: 600;
}

.sample-card ul {
    display: grid;
    gap: 0.5rem;
    padding: 0;
    list-style: none;
}

.sample-card button {
    display: inline-flex;
    align-items: center;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.sample-card button:focus-visible,
.sample-card .name:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
