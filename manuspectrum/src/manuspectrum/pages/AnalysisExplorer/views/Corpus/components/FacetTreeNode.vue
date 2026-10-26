<script setup lang="ts">
import { computed, inject } from "vue";
import { useGettext } from "vue3-gettext";

import FacetMark from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetMark.vue";
import FacetTreeNode from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetTreeNode.vue";

import {
    ICON_VIEW_BOX,
    ICONS,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import { FACET_TREE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/facet-tree.ts";

import type { TreeNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/facet-tree.ts";

/**
 * One occurrence of a value in `FacetTree`: its unfold button when it has
 * children (a leaf keeps the same room, so checkboxes align by level), then
 * its native checkbox, mark (`FacetMark`), label, « unpublished » badge and
 * count, then, once unfolded, the list of its children under a guide line.
 * Labels, paths and « covered by X » wrap, never cut. A
 * covered value keeps a focusable checkbox, ticked in a pale tone and
 * `aria-disabled`, described by « covered by X » under its label; its click
 * is cancelled, so neither the pointer nor Space changes it. In the flat
 * list (`flat`) each of its `paths` is a line under its label and it never
 * unfolds.
 */
const props = withDefaults(
    defineProps<{
        node: TreeNode;
        paths?: readonly string[];
        flat?: boolean;
    }>(),
    { paths: () => [], flat: false },
);

const { $gettext } = useGettext();
const tree = inject(FACET_TREE_KEY);
if (!tree) {
    throw new Error("FacetTreeNode is drawn by FacetTree");
}

const state = computed(() => tree.stateOf(props.node.value.id));
const covered = computed(() => state.value === "implicit");
const coveredText = computed(() => tree.coveredText(props.node.value.id));
const coveredId = computed(() => `${tree.nodeId(props.node)}-covered`);
const listId = computed(() => `${tree.nodeId(props.node)}-list`);
const hasChildren = computed(
    () => !props.flat && props.node.children.length > 0,
);
const isOpen = computed(() => hasChildren.value && tree.isOpen(props.node));
const isDisabled = computed(
    () => props.node.value.count === 0 && state.value === "none",
);

function onClick(event: MouseEvent): void {
    if (covered.value) event.preventDefault();
}
</script>

<template>
    <li
        class="node"
        :class="{
            leaf: !hasChildren,
            flat: props.flat,
            implicit: covered,
        }"
    >
        <div class="row">
            <button
                v-if="hasChildren"
                type="button"
                class="expander"
                :aria-expanded="isOpen ? 'true' : 'false'"
                :aria-controls="listId"
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
            <label class="value">
                <input
                    type="checkbox"
                    :value="props.node.value.id"
                    :checked="state === 'checked' || covered"
                    :indeterminate="state === 'mixed'"
                    :disabled="isDisabled"
                    :aria-disabled="covered ? 'true' : undefined"
                    :aria-describedby="covered ? coveredId : undefined"
                    @click="onClick"
                    @change="tree.change(props.node.value.id)"
                />
                <FacetMark
                    :facet-key="tree.facetKey"
                    :mark="props.node.value.mark"
                    :swatch="props.node.value.swatch"
                />
                <span class="text">
                    <span
                        class="label"
                        :lang="props.node.value.label.lang"
                        >{{ props.node.value.label.value }}</span
                    >
                    <span
                        v-for="path in props.paths"
                        :key="path"
                        class="path"
                        >{{ path }}</span
                    >
                    <span
                        v-if="covered"
                        :id="coveredId"
                        class="covered"
                        >{{ coveredText }}</span
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
            :id="listId"
            class="children"
        >
            <FacetTreeNode
                v-for="child in props.node.children"
                :key="child.key"
                :node="child"
            />
        </ul>
    </li>
</template>

<style scoped>
.node .row {
    display: flex;
    align-items: flex-start;
    gap: 0.25rem;
}

.tree.has-branches .node.leaf:not(.flat) > .row::before {
    content: "";
    flex: none;
    inline-size: 1.5rem;
}

.node .expander {
    display: inline-flex;
    flex: none;
    inline-size: 1.5rem;
    block-size: var(--explorer-target, 2rem);
    align-items: flex-start;
    justify-content: center;
    padding: 0.34375rem 0 0;
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
    align-items: flex-start;
    gap: 0.375rem;
    min-block-size: var(--explorer-target, 2rem);
    min-inline-size: 0;
    padding-block: 0.3125rem;
    font-size: 0.8125rem;
    line-height: 1.3;
    cursor: pointer;
}

.node .value input {
    flex: none;
    margin-block-start: 0.125rem;
}

.node .value .facet-mark {
    margin-block-start: 0.25rem;
}

.node .value:has(input:disabled) {
    color: var(--ink-dim);
    cursor: default;
}

.node.implicit > .row .value {
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
.node .path,
.node .covered {
    overflow-wrap: break-word;
    hyphens: auto;
    hyphenate-limit-chars: 10 4 4;
    text-wrap: pretty;
}

.node .path,
.node .covered {
    color: var(--ink-muted);
    font-size: 0.6875rem;
}

.node .covered {
    font-style: italic;
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
    min-inline-size: 2.25rem;
    padding-block-start: 0.0625rem;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    text-align: end;
}

.node .children {
    margin-inline-start: 0.75rem;
    padding-inline-start: 0.25rem;
    border-inline-start: 0.0625rem solid var(--border-hover);
    list-style: none;
}
</style>
