<script setup lang="ts">
import { computed, provide, ref, useId } from "vue";
import { useGettext } from "vue3-gettext";

import FacetTreeNode from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetTreeNode.vue";

import {
    ancestorIds,
    buildTree,
    coveringIds,
    domToken,
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

const FLAT_KEY_PREFIX = "flat:";

/**
 * A facet whose values form a tree through their `parents` (places, terms of
 * a controlled list), as nested lists of native checkboxes, each parent with
 * a button to unfold it (no `role="tree"`). A value with several parents is
 * drawn under each; every occurrence shows the one state of the value
 * (`nodeState`), and folding and DOM ids go by occurrence (`TreeNode.key`).
 * Counts are the server's. Ticking a value covers its narrower terms: they
 * read ticked in a pale tone, `aria-disabled`, with « covered by X » under
 * the label, and a click on them changes nothing. The ancestors of a ticked
 * value are mixed. Only the roots are shown, with the ancestors of the
 * ticked values opened on every path, unless `expandedByDefault`; a fold or
 * unfold by hand wins. A typed `query` replaces the tree by a flat list, one
 * entry per value with each of its paths: the `found` ids when the server
 * gave them (synonyms included), else the values whose label holds the
 * query. `values` are the values to draw, `selected` the ticked ids (what
 * the filters hold), `countHint` says what a count counts.
 */
const props = withDefaults(
    defineProps<{
        facet: Facet;
        values: FacetValue[];
        selected: readonly string[];
        countHint?: string;
        expandedByDefault?: boolean;
        query?: string;
        found?: readonly string[] | null;
        busy?: boolean;
    }>(),
    {
        countHint: "",
        expandedByDefault: false,
        query: "",
        found: null,
        busy: false,
    },
);
const emit = defineEmits<{ change: [ids: string[]] }>();

const gettext = useGettext();
const { $gettext, interpolate } = gettext;
const baseId = useId();

/** What the reader folded or unfolded by hand, by occurrence key; it wins over the default. */
const manual = ref<Record<string, boolean>>({});

const tree = computed(() => buildTree(props.values));
const searching = computed(() => props.query.trim() !== "");
const flatEntries = computed(() =>
    flatten(props.values, props.query, props.found).map((entry) => ({
        node: {
            value: entry.value,
            children: [],
            key: `${FLAT_KEY_PREFIX}${entry.value.id}`,
        } satisfies TreeNode,
        paths: entry.paths.filter((path) => path !== ""),
    })),
);
const openByTick = computed(
    () =>
        new Set(
            props.selected.flatMap((id) => [...ancestorIds(id, props.values)]),
        ),
);
const states = computed(
    () =>
        new Map(
            props.values.map((value) => [
                value.id,
                nodeState(value.id, props.selected, props.values),
            ]),
        ),
);
const labels = computed(
    () => new Map(props.values.map((value) => [value.id, value.label.value])),
);

function isOpen(node: TreeNode): boolean {
    return (
        manual.value[node.key] ??
        (props.expandedByDefault || openByTick.value.has(node.value.id))
    );
}

function toggleOpen(node: TreeNode): void {
    manual.value = { ...manual.value, [node.key]: !isOpen(node) };
}

function stateOf(id: string): NodeState {
    return states.value.get(id) ?? "none";
}

function coveredText(id: string): string {
    if (stateOf(id) !== "implicit") return "";
    const terms = coveringIds(id, props.selected, props.values).map(
        (covering) => labels.value.get(covering) ?? covering,
    );
    return interpolate(
        $gettext("covered by %{terms}"),
        {
            terms: new Intl.ListFormat(gettext.current, {
                type: "conjunction",
            }).format(terms),
        },
        true,
    );
}

function change(id: string): void {
    if (stateOf(id) === "implicit") return;
    emit("change", toggle(id, props.selected, props.values));
}

function nodeId(node: TreeNode): string {
    return `${baseId}-${domToken(node.key)}`;
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
    facetKey: props.facet.key,
    isOpen,
    toggleOpen,
    stateOf,
    coveredText,
    change,
    nodeId,
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
            :key="entry.node.key"
            :node="entry.node"
            :paths="entry.paths"
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
            :key="root.key"
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
