<script setup lang="ts">
import { computed, ref } from "vue";
import { useGettext } from "vue3-gettext";

import { techniqueKey } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";

import type {
    CharacterizationSummary,
    SampleSummary,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    Annotation,
    UnlocatedAnalysis,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/document-view.ts";
import type { TechniqueStyle } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import type {
    Focus,
    FolioView,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const SEPARATOR = /\s+[—–-]\s+/;

/**
 * What the page shows, listed. A row name drops the page label and the
 * document it ends with (`pageLabel`, `documentName`: the screen says them
 * already). The analyses without a position fold under their count when
 * the page has analyses of its own.
 */
const props = withDefaults(
    defineProps<{
        annotations: Annotation[];
        unlocated: UnlocatedAnalysis[];
        characterizations: CharacterizationSummary[];
        samples: SampleSummary[];
        styles: Map<string, TechniqueStyle>;
        view: FolioView;
        pageLabel?: string;
        documentName?: string;
    }>(),
    { pageLabel: "", documentName: "" },
);
const emit = defineEmits<{ select: [focus: Focus] }>();

const { $gettext, interpolate } = useGettext();

const unlocatedOpen = ref(props.annotations.length === 0);

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

/** The message of a view with nothing to list; null when the view lists something. */
const emptyMessage = computed(() => {
    if (props.view === "characterizations") {
        return props.characterizations.length === 0
            ? $gettext("No identified material on this page.")
            : null;
    }
    if (props.view === "samples") {
        return props.samples.length === 0
            ? $gettext("No sample on this page.")
            : null;
    }
    return props.annotations.length === 0 && props.unlocated.length === 0
        ? $gettext("No published analysis on this page.")
        : null;
});

const unlocatedTitle = computed(() =>
    interpolate(
        $gettext("Without a position on the image (%{n})"),
        { n: props.unlocated.length },
        true,
    ),
);

/**
 * `name` without its trailing context: from the segment that is this page's
 * label when at most one segment (the document) follows it, else without a
 * last segment that is the document's name. Segments are separated by a
 * spaced dash.
 */
function shortName(name: string): string {
    const parts = name.split(SEPARATOR);
    const page = props.pageLabel.trim();
    const at = page ? parts.lastIndexOf(page) : -1;
    if (at >= 1 && at >= parts.length - 2) {
        return parts.slice(0, at).join(" — ");
    }
    const document = props.documentName.trim();
    if (parts.length > 1 && document && parts.at(-1) === document) {
        return parts.slice(0, -1).join(" — ");
    }
    return name;
}

function toggleUnlocated(): void {
    unlocatedOpen.value = !unlocatedOpen.value;
}

function select(focus: Focus): void {
    emit("select", focus);
}
</script>

<template>
    <section
        class="on-this-page"
        aria-labelledby="on-this-page-title"
    >
        <h3
            id="on-this-page-title"
            tabindex="-1"
        >
            <span>{{ $gettext("On this page") }}</span>
        </h3>
        <p
            v-if="emptyMessage"
            class="empty"
        >
            <span>{{ emptyMessage }}</span>
        </p>
        <template v-if="props.view === 'analyses'">
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
                            :data-focus="`analysis:${item.analysis}`"
                            :title="item.name.value"
                            @click="
                                select({ kind: 'analysis', id: item.analysis })
                            "
                        >
                            <span :lang="item.name.lang">{{
                                shortName(item.name.value)
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
        </template>
        <section
            v-if="
                props.view === 'characterizations' &&
                props.characterizations.length > 0
            "
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
                        :data-focus="`characterization:${summary.id}`"
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
            v-if="props.view === 'samples' && props.samples.length > 0"
            class="samples"
        >
            <h4>
                <span>{{ $gettext("Samples") }}</span>
            </h4>
            <ul>
                <li
                    v-for="entry in props.samples"
                    :key="entry.id"
                >
                    <button
                        type="button"
                        :data-focus="`sample:${entry.id}`"
                        @click="select({ kind: 'sample', id: entry.id })"
                    >
                        <span :lang="entry.name.lang">{{
                            entry.name.value
                        }}</span>
                    </button>
                    <span
                        v-if="entry.unpublished"
                        class="draft"
                    >
                        {{ $gettext("Draft") }}
                    </span>
                </li>
            </ul>
        </section>
        <section
            v-if="props.view === 'analyses' && props.unlocated.length > 0"
            class="unlocated"
        >
            <h4>
                <button
                    type="button"
                    class="fold"
                    :aria-expanded="unlocatedOpen ? 'true' : 'false'"
                    @click="toggleUnlocated"
                >
                    <span>{{ unlocatedTitle }}</span>
                </button>
            </h4>
            <ul v-if="unlocatedOpen">
                <li
                    v-for="item in props.unlocated"
                    :key="item.analysis"
                    :class="{ 'is-dimmed': !item.match }"
                >
                    <button
                        type="button"
                        :data-focus="`unlocated:${item.analysis}`"
                        :title="item.name.value"
                        @click="select({ kind: 'analysis', id: item.analysis })"
                    >
                        <span :lang="item.name.lang">{{
                            shortName(item.name.value)
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
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-weight: 400;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.on-this-page h3:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
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
    font-size: 0.8125rem;
    font-weight: 600;
}

.on-this-page .code {
    display: inline-grid;
    flex: none;
    place-items: center;
    box-sizing: border-box;
    min-inline-size: 1.5rem;
    block-size: 1.5rem;
    padding-inline: 0.25rem;
    border: 0.125rem solid var(--surface);
    border-radius: 999rem;
    background: var(--ink);
    color: var(--stage);
    font: 600 0.625rem var(--font-body);
    white-space: nowrap;
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

.on-this-page .code--tech-7 {
    background: var(--tech-7);
}

.on-this-page .code--tech-8 {
    background: var(--tech-8);
}

.on-this-page .code--tech-9 {
    background: var(--tech-9);
}

.on-this-page .code--tech-10 {
    background: var(--tech-10);
}

.on-this-page .code--ink {
    border-color: var(--ink);
    background: var(--surface);
    color: var(--ink);
}

.on-this-page ul {
    display: grid;
    gap: 0;
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
    min-block-size: var(--explorer-target, 2.75rem);
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

.on-this-page .fold {
    font-weight: 600;
}

.on-this-page .fold::before {
    content: "▸" / "";
    margin-inline-end: 0.375rem;
}

.on-this-page .fold[aria-expanded="true"]::before {
    content: "▾" / "";
}

.on-this-page .draft,
.on-this-page .outside {
    color: var(--ink-muted);
    font-size: 0.75rem;
}
</style>
