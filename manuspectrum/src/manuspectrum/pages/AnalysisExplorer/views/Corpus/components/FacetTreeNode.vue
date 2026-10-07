<script setup lang="ts">
import { computed, inject } from "vue";
import { useGettext } from "vue3-gettext";

import FacetTreeNode from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetTreeNode.vue";

import {
    ICON_VIEW_BOX,
    ICONS,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import { FACET_TREE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/facet-tree.ts";

import type { TreeNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/facet-tree.ts";

/**
 * One place of `FacetTree`: its unfold button (when it has children), its
 * native checkbox, label, « unpublished » badge and count, then, once
 * unfolded, the list of its children. In the flat list (`path` given, `flat`)
 * it shows the path of the place under its label and never unfolds.
 */
const props = withDefaults(
    defineProps<{ node: TreeNode; path?: string; flat?: boolean }>(),
    { path: "", flat: false },
);

const { $gettext } = useGettext();
const tree = inject(FACET_TREE_KEY);
if (!tree) {
    throw new Error("FacetTreeNode is drawn by FacetTree");
}

const state = computed(() => tree.stateOf(props.node));
const hasChildren = computed(
    () => !props.flat && props.node.children.length > 0,
);
const isOpen = computed(() => hasChildren.value && tree.isOpen(props.node));
const isDisabled = computed(
    () => props.node.value.count === 0 && state.value === "none",
);
</script>

<template>
    <li
        class="node"
        :class="{
            leaf: !hasChildren,
            implicit: state === 'implicit',
        }"
    >
        <div class="row">
            <button
                v-if="hasChildren"
                type="button"
                class="expander"
                :aria-expanded="isOpen ? 'true' : 'false'"
                :aria-controls="tree.listId(props.node)"
                :aria-label="tree.expanderLabel(props.node)"
                @click="tree.toggleOpen(props.node)"
            >
                <svg
                    class="chevron"
                    aria-hidden="true"
                    focusable="false"
                    :viewBox="ICON_VIEW_BOX"
                >
                    <path
                        v-for="(shape, index) in ICONS[
                            isOpen ? 'chevron-down' : 'chevron-right'
                        ]"
                        :key="index"
                        :d="shape"
                    />
                </svg>
            </button>
            <span
                v-else
                class="expander-gap"
                aria-hidden="true"
            ></span>
            <label class="value">
                <input
                    type="checkbox"
                    :value="props.node.value.id"
                    :checked="state === 'checked' || state === 'implicit'"
                    :indeterminate="state === 'mixed'"
                    :disabled="isDisabled"
                    @change="tree.change(props.node)"
                />
                <span class="text">
                    <span
                        class="label"
                        :lang="props.node.value.label.lang"
                        >{{ props.node.value.label.value }}</span
                    >
                    <span
                        v-if="props.path"
                        class="path"
                        >{{ props.path }}</span
                    >
                </span>
                <span
                    v-if="props.node.value.unpublished"
                    class="unpublished"
                    >{{ $gettext("unpublished") }}</span
                >
                <span
                    class="count"
                    :title="tree.countTitle(props.node.value)"
                    >{{ props.node.value.count }}</span
                >
            </label>
        </div>
        <ul
            v-if="isOpen"
            :id="tree.listId(props.node)"
            class="children"
        >
            <FacetTreeNode
                v-for="child in props.node.children"
                :key="child.value.id"
                :node="child"
            />
        </ul>
    </li>
</template>

<style scoped>
.node .row {
    display: flex;
    align-items: center;
    gap: 0.25rem;
}

.node .expander,
.node .expander-gap {
    flex: none;
    inline-size: var(--explorer-target, 2.75rem);
    min-block-size: var(--explorer-target, 2.75rem);
}

.node .expander {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--ink-muted);
    cursor: pointer;
}

.node .expander:hover {
    color: var(--ink);
}

.node .expander:focus-visible,
.node .value input:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.node .chevron {
    inline-size: 1rem;
    block-size: 1rem;
    fill: currentcolor;
}

.node .value {
    display: flex;
    flex: 1 1 auto;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2.75rem);
    min-inline-size: 0;
    font-size: 0.8125rem;
    cursor: pointer;
}

.node .value:has(input:disabled) {
    color: var(--ink-dim);
    cursor: default;
}

.node.implicit > .row .value input {
    opacity: 0.55;
}

.node .text {
    display: grid;
    flex: 1 1 auto;
    min-inline-size: 0;
}

.node .label,
.node .path {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.node .path {
    color: var(--ink-muted);
    font-size: 0.6875rem;
}

.node .unpublished {
    flex: none;
    padding-inline: 0.375rem;
    border: 0.0625rem solid var(--accent-text);
    border-radius: 999rem;
    color: var(--accent-text);
    font-size: 0.6875rem;
}

.node .count {
    flex: none;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    text-align: end;
}

.node .children {
    margin-inline-start: 1.25rem;
    list-style: none;
}
</style>
