<script setup lang="ts">
import { computed, ref, useId } from "vue";
import { useGettext } from "vue3-gettext";

import TechniqueTag from "@/manuspectrum/pages/AnalysisExplorer/components/TechniqueTag.vue";
import LinkedChip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LinkedChip.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { analysisNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type {
    NamedRef,
    Technique,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

interface TechniqueCount {
    technique: Technique;
    count: number;
}

/**
 * The analyses cited as evidence: their number, a button unfolding them
 * (`aria-expanded`), and the techniques of those whose technique is known
 * (`techniques`, by analysis id), each with its count. Unfolded, each
 * analysis is a toggle of its node (`LinkedChip`) when the linked
 * selection holds it, plain text otherwise. Without any, a dash.
 */
const props = defineProps<{
    evidence: readonly NamedRef[];
    techniques: ReadonlyMap<string, Technique>;
}>();

const { $gettext, $ngettext, interpolate } = useGettext();
const marks = useLinkedMarks();
const listId = useId();

const open = ref(false);

const counted = computed<TechniqueCount[]>(() => {
    const counts = new Map<string, TechniqueCount>();
    for (const entry of props.evidence) {
        const technique = props.techniques.get(entry.id);
        if (!technique) continue;
        const found = counts.get(technique.id) ?? { technique, count: 0 };
        found.count += 1;
        counts.set(technique.id, found);
    }
    return [...counts.values()];
});
const countText = computed(() =>
    interpolate(
        $ngettext("%{n} analysis", "%{n} analyses", props.evidence.length),
        { n: props.evidence.length },
        true,
    ),
);

function canToggle(id: string): boolean {
    return (
        !marks.linked || marks.linked.graph.value.nodes.has(analysisNode(id))
    );
}

function toggleOpen(): void {
    open.value = !open.value;
}
</script>

<template>
    <div
        v-if="props.evidence.length > 0"
        class="material-evidence"
    >
        <button
            type="button"
            class="expander"
            :aria-expanded="open ? 'true' : 'false'"
            :aria-controls="open ? listId : undefined"
            @click="toggleOpen"
        >
            <span>{{ countText }}</span>
            <span
                class="caret"
                aria-hidden="true"
                >▾</span
            >
        </button>
        <span
            v-if="counted.length > 0"
            class="techniques"
        >
            <span
                v-for="entry in counted"
                :key="entry.technique.id"
                class="technique"
            >
                <TechniqueTag
                    :code="entry.technique.code"
                    :colour="entry.technique.colour"
                />
                <small v-if="entry.count > 1">×{{ entry.count }}</small>
            </span>
        </span>
        <ul
            v-if="open"
            :id="listId"
            class="analyses"
        >
            <li
                v-for="entry in props.evidence"
                :key="entry.id"
            >
                <LinkedChip
                    v-if="canToggle(entry.id)"
                    :node="analysisNode(entry.id)"
                    :text="entry.name.value"
                    :lang="entry.name.lang"
                />
                <span
                    v-else
                    class="plain"
                    :lang="entry.name.lang"
                    >{{ entry.name.value }}</span
                >
            </li>
        </ul>
    </div>
    <span
        v-else
        class="material-evidence none"
    >
        <span aria-hidden="true">—</span>
        <span class="visually-hidden">{{ $gettext("Not stated") }}</span>
    </span>
</template>

<style scoped>
.material-evidence {
    display: grid;
    gap: 0.25rem;
}

.material-evidence .expander {
    display: inline-flex;
    justify-self: start;
    align-items: center;
    gap: 0.3125rem;
    min-block-size: 1.5rem;
    margin-inline-start: -0.375rem;
    padding-inline: 0.375rem;
    border: none;
    border-radius: 0.375rem;
    background: transparent;
    color: var(--ink);
    font: inherit;
    font-size: 0.78125rem;
    font-weight: 600;
    white-space: nowrap;
    cursor: pointer;
}

.material-evidence .expander:hover {
    background: var(--bg-alt);
}

.material-evidence .expander:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.1875rem;
}

.material-evidence .caret {
    color: var(--ink-muted);
    font-size: 0.6875rem;
    transition: transform var(--dur-fast, 160ms);
}

.material-evidence .expander[aria-expanded="false"] .caret {
    transform: rotate(-90deg);
}

.material-evidence .techniques {
    display: flex;
    flex-wrap: wrap;
    gap: 0.125rem 0.5rem;
}

.material-evidence .technique {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.6875rem;
    white-space: nowrap;
}

.material-evidence .technique small {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.625rem;
}

.material-evidence .analyses {
    display: flex;
    flex-wrap: wrap;
    gap: var(--focus-room) 0.25rem;
    margin: 0;
    padding: 0;
    padding-block-start: var(--focus-room);
    list-style: none;
}

.material-evidence .analyses .linked-chip {
    --chip-max: 10.5rem;
}

.material-evidence .plain {
    font-size: 0.75rem;
}

.material-evidence.none {
    display: inline;
    color: var(--ink-dim);
}

.material-evidence .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

@media (prefers-reduced-motion: reduce) {
    .material-evidence .caret {
        transition: none;
    }
}
</style>
