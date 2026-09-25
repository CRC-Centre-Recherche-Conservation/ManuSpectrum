<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import { techniqueKey } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";

import type {
    Annotation,
    CharacterizationSummary,
    UnlocatedAnalysis,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { TechniqueStyle } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import type { Focus } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const props = defineProps<{
    annotations: Annotation[];
    unlocated: UnlocatedAnalysis[];
    characterizations: CharacterizationSummary[];
    styles: Map<string, TechniqueStyle>;
}>();
const emit = defineEmits<{ select: [focus: Focus] }>();

const { $gettext } = useGettext();

/** One entry per analysis (an analysis may have several zones), grouped in the order of the technique styles. */
const groups = computed(() => {
    const seen = new Set<string>();
    const byTechnique = new Map<string, Annotation[]>();
    for (const annotation of props.annotations) {
        if (seen.has(annotation.analysis)) continue;
        seen.add(annotation.analysis);
        const key = techniqueKey(annotation.technique);
        byTechnique.set(key, [...(byTechnique.get(key) ?? []), annotation]);
    }
    return [...props.styles.values()]
        .filter((style) => byTechnique.has(style.key))
        .map((style) => ({ style, items: byTechnique.get(style.key)! }));
});

const isEmpty = computed(
    () =>
        props.annotations.length === 0 &&
        props.unlocated.length === 0 &&
        props.characterizations.length === 0,
);

function select(focus: Focus): void {
    emit("select", focus);
}
</script>

<template>
    <section
        class="on-this-page"
        aria-labelledby="on-this-page-title"
    >
        <h3 id="on-this-page-title">
            <span>{{ $gettext("On this page") }}</span>
        </h3>
        <p
            v-if="isEmpty"
            class="empty"
        >
            <span>{{ $gettext("No published analysis on this page.") }}</span>
        </p>
        <section
            v-for="group in groups"
            :key="group.style.key"
            class="technique"
        >
            <h4>
                <span
                    class="code"
                    :class="
                        group.style.colour
                            ? `code--tech-${group.style.colour}`
                            : 'code--ink'
                    "
                    aria-hidden="true"
                >
                    {{ group.style.code }}
                </span>
                <span :lang="group.style.label.lang || undefined">
                    {{ group.style.label.value }}
                </span>
            </h4>
            <ul>
                <li
                    v-for="item in group.items"
                    :key="item.analysis"
                    :class="{ 'is-dimmed': !item.match }"
                >
                    <button
                        type="button"
                        @click="select({ kind: 'analysis', id: item.analysis })"
                    >
                        <span :lang="item.name.lang">{{
                            item.name.value
                        }}</span>
                    </button>
                    <span
                        v-if="item.unpublished"
                        class="draft"
                    >
                        {{ $gettext("Draft") }}
                    </span>
                    <span
                        v-if="!item.match"
                        class="outside"
                    >
                        {{ $gettext("outside the filters") }}
                    </span>
                </li>
            </ul>
        </section>
        <section
            v-if="props.characterizations.length > 0"
            class="materials"
        >
            <h4>
                <span>{{ $gettext("Identified materials") }}</span>
            </h4>
            <ul>
                <li
                    v-for="summary in props.characterizations"
                    :key="summary.id"
                >
                    <button
                        type="button"
                        @click="
                            select({ kind: 'characterization', id: summary.id })
                        "
                    >
                        <span :lang="summary.name.lang">{{
                            summary.name.value
                        }}</span>
                    </button>
                    <span
                        v-if="summary.unpublished"
                        class="draft"
                    >
                        {{ $gettext("Draft") }}
                    </span>
                </li>
            </ul>
        </section>
        <section
            v-if="props.unlocated.length > 0"
            class="unlocated"
        >
            <h4>
                <span>{{ $gettext("Without a position on the image") }}</span>
            </h4>
            <ul>
                <li
                    v-for="item in props.unlocated"
                    :key="item.analysis"
                    :class="{ 'is-dimmed': !item.match }"
                >
                    <button
                        type="button"
                        @click="select({ kind: 'analysis', id: item.analysis })"
                    >
                        <span :lang="item.name.lang">{{
                            item.name.value
                        }}</span>
                    </button>
                    <span
                        v-if="item.unpublished"
                        class="draft"
                    >
                        {{ $gettext("Draft") }}
                    </span>
                    <span
                        v-if="!item.match"
                        class="outside"
                    >
                        {{ $gettext("outside the filters") }}
                    </span>
                </li>
            </ul>
        </section>
    </section>
</template>

<style scoped>
.on-this-page {
    display: grid;
    gap: 1rem;
}

.on-this-page h3 {
    font-weight: 600;
}

.on-this-page .empty {
    color: var(--ink-muted);
}

.on-this-page section {
    display: grid;
    gap: 0.5rem;
}

.on-this-page h4 {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-weight: 600;
}

.on-this-page .code {
    display: inline-grid;
    place-items: center;
    inline-size: 1.5rem;
    block-size: 1.5rem;
    border: 0.125rem solid var(--surface);
    border-radius: 50%;
    background: var(--ink);
    color: var(--stage);
    font: 600 0.6875rem var(--font-body);
}

.on-this-page .code--tech-1 {
    background: var(--tech-1);
}

.on-this-page .code--tech-2 {
    background: var(--tech-2);
}

.on-this-page .code--tech-3 {
    background: var(--tech-3);
}

.on-this-page .code--tech-4 {
    background: var(--tech-4);
}

.on-this-page .code--tech-5 {
    background: var(--tech-5);
}

.on-this-page .code--tech-6 {
    background: var(--tech-6);
}

.on-this-page .code--ink {
    background: var(--surface);
    color: var(--ink);
}

.on-this-page ul {
    display: grid;
    gap: 0.25rem;
    padding: 0;
    list-style: none;
}

.on-this-page li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
}

.on-this-page li.is-dimmed {
    opacity: 0.55;
}

.on-this-page button {
    display: inline-flex;
    flex: 1 1 auto;
    align-items: center;
    justify-content: flex-start;
    min-block-size: 2.75rem;
    padding-inline: 0.5rem;
    border: none;
    border-radius: 0.25rem;
    background: none;
    color: var(--ink);
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.on-this-page button:hover {
    background: var(--bg-alt);
}

.on-this-page button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.on-this-page .draft,
.on-this-page .outside {
    color: var(--ink-muted);
    font-size: 0.75rem;
}
</style>
