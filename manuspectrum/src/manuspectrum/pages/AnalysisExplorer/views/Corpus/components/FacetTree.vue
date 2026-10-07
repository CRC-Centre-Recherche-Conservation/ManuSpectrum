<script setup lang="ts">
import { computed, provide, ref, useId } from "vue";
import { useGettext } from "vue3-gettext";

import FacetTreeNode from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetTreeNode.vue";

import {
    ancestorsOf,
    buildTree,
    FACET_TREE_KEY,
    flatten,
    nodeState,
    toggle,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/facet-tree.ts";

import type {
    Facet,
    FacetValue,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    FacetTreeContext,
    NodeState,
    TreeNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/facet-tree.ts";

/**
 * A facet whose values form a tree through their `parent` (the places), as
 * nested lists of native checkboxes, each parent with a button to unfold it
 * (no `role="tree"`). Counts are the server's. Ticking a parent covers its
 * descendants, drawn ticked in a pale tone (implicit); the ancestors of a
 * ticked place are mixed. Everything is folded but the ancestors of the ticked
 * places, unless `expandedByDefault`. A typed `query` replaces the tree by the
 * matching places in a flat list, each with its path. `values` are the places
 * to draw, `selected` the ticked ids (what the filters hold), `countHint`
 * says what a count counts.
 */
const props = withDefaults(
    defineProps<{
        facet: Facet;
        values: FacetValue[];
        selected: readonly string[];
        countHint?: string;
        expandedByDefault?: boolean;
        query?: string;
        busy?: boolean;
    }>(),
    { countHint: "", expandedByDefault: false, query: "", busy: false },
);
const emit = defineEmits<{ change: [ids: string[]] }>();

const { $gettext, interpolate } = useGettext();
const baseId = useId();

/** What the reader folded or unfolded by hand, by id; it wins over the default. */
const manual = ref<Record<string, boolean>>({});

const tree = computed(() => buildTree(props.values));
const searching = computed(() => props.query.trim() !== "");
const flatEntries = computed(() => flatten(tree.value, props.query));
const openByTick = computed(
    () => new Set(props.selected.flatMap((id) => ancestorsOf(id, tree.value))),
);

function isOpen(node: TreeNode): boolean {
    return (
        manual.value[node.value.id] ??
        (props.expandedByDefault || openByTick.value.has(node.value.id))
    );
}

function toggleOpen(node: TreeNode): void {
    manual.value = { ...manual.value, [node.value.id]: !isOpen(node) };
}

function stateOf(node: TreeNode): NodeState {
    return nodeState(node, props.selected, tree.value);
}

function change(node: TreeNode): void {
    emit("change", toggle(node, props.selected, tree.value));
}

function listId(node: TreeNode): string {
    return `${baseId}-${node.value.id}`;
}

function expanderLabel(node: TreeNode): string {
    return interpolate(
        isOpen(node) ? $gettext("Fold %{place}") : $gettext("Unfold %{place}"),
        { place: node.value.label.value },
        true,
    );
}

function countTitle(value: FacetValue): string | undefined {
    return props.countHint
        ? interpolate(props.countHint, { n: value.count }, true)
        : undefined;
}

const context: FacetTreeContext = {
    isOpen,
    toggleOpen,
    stateOf,
    change,
    listId,
    countTitle,
    expanderLabel,
};
provide(FACET_TREE_KEY, context);
</script>

<template>
    <ul
        v-if="searching"
        class="tree flat"
        :class="{ busy: props.busy }"
        :aria-busy="props.busy ? 'true' : 'false'"
    >
        <FacetTreeNode
            v-for="entry in flatEntries"
            :key="entry.node.value.id"
            :node="entry.node"
            :path="entry.path"
            :flat="true"
        />
    </ul>
    <ul
        v-else
        class="tree"
        :class="{ busy: props.busy }"
        :aria-busy="props.busy ? 'true' : 'false'"
    >
        <FacetTreeNode
            v-for="root in tree"
            :key="root.value.id"
            :node="root"
        />
    </ul>
</template>

<style scoped>
.tree {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    list-style: none;
}

.tree.busy {
    opacity: 0.6;
}
</style>
