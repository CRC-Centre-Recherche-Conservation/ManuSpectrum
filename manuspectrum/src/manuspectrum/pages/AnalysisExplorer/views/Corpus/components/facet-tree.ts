import type { InjectionKey } from "vue";

import { foldText } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";

import type { FacetValue } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

export interface TreeNode {
    value: FacetValue;
    children: TreeNode[];
}

export type NodeState = "checked" | "implicit" | "mixed" | "none";

export interface FlatEntry {
    node: TreeNode;
    /** The ancestors' labels, nearest first, joined by « — »; empty for a root. */
    path: string;
}

/** Facets with more values than this offer a search box. */
export const SEARCH_THRESHOLD = 8;
const PATH_SEPARATOR = " — ";

function byLabel(a: TreeNode, b: TreeNode): number {
    const left = foldText(a.value.label.value);
    const right = foldText(b.value.label.value);
    return left < right ? -1 : left > right ? 1 : 0;
}

/**
 * The forest of `values` by their `parent`: a value with no parent, or whose
 * parent is not among `values`, is a root; siblings are ordered by folded
 * label. A value caught in a cycle of parents is unreachable and dropped.
 */
export function buildTree(values: readonly FacetValue[]): TreeNode[] {
    const nodes = new Map<string, TreeNode>(
        values.map((value) => [value.id, { value, children: [] }]),
    );
    const roots: TreeNode[] = [];
    for (const node of nodes.values()) {
        const parent = node.value.parent
            ? nodes.get(node.value.parent)
            : undefined;
        if (parent && parent !== node) {
            parent.children.push(node);
        } else if (!parent || parent === node) {
            roots.push(node);
        }
    }
    for (const node of nodes.values()) node.children.sort(byLabel);
    return roots.sort(byLabel);
}

/** The nodes of `tree` by id, each with its parent node. */
function indexOf(
    tree: readonly TreeNode[],
): Map<string, { node: TreeNode; parent: TreeNode | null }> {
    const index = new Map<
        string,
        { node: TreeNode; parent: TreeNode | null }
    >();
    function visit(nodes: readonly TreeNode[], parent: TreeNode | null): void {
        for (const node of nodes) {
            index.set(node.value.id, { node, parent });
            visit(node.children, node);
        }
    }
    visit(tree, null);
    return index;
}

/** The ids above `id`, nearest first; none for a root or an unknown id. */
export function ancestorsOf(id: string, tree: readonly TreeNode[]): string[] {
    const index = indexOf(tree);
    const found: string[] = [];
    let parent = index.get(id)?.parent ?? null;
    while (parent) {
        found.push(parent.value.id);
        parent = index.get(parent.value.id)?.parent ?? null;
    }
    return found;
}

function descendantIds(node: TreeNode): string[] {
    return node.children.flatMap((child) => [
        child.value.id,
        ...descendantIds(child),
    ]);
}

/** Ticked, under a ticked ancestor (implicit), above a ticked descendant (mixed), or none of these. */
export function nodeState(
    node: TreeNode,
    selected: readonly string[],
    tree: readonly TreeNode[],
): NodeState {
    if (selected.includes(node.value.id)) return "checked";
    if (ancestorsOf(node.value.id, tree).some((id) => selected.includes(id))) {
        return "implicit";
    }
    if (descendantIds(node).some((id) => selected.includes(id))) return "mixed";
    return "none";
}

/**
 * The ticked ids after a click on `node`. Ticking drops the ticked
 * descendants (the node already covers them); unticking a ticked node removes
 * it; unticking an implicit node removes its nearest ticked ancestor and ticks,
 * along the path down to the node, every sibling it did not cover through
 * the node.
 */
export function toggle(
    node: TreeNode,
    selected: readonly string[],
    tree: readonly TreeNode[],
): string[] {
    const state = nodeState(node, selected, tree);
    if (state === "checked") {
        return selected.filter((id) => id !== node.value.id);
    }
    if (state === "implicit") {
        const index = indexOf(tree);
        const path: TreeNode[] = [node];
        let parent = index.get(node.value.id)?.parent ?? null;
        while (parent && !selected.includes(parent.value.id)) {
            path.unshift(parent);
            parent = index.get(parent.value.id)?.parent ?? null;
        }
        if (!parent) return [...selected];
        const added: string[] = [];
        let above: TreeNode = parent;
        for (const step of path) {
            for (const child of above.children) {
                if (child !== step) added.push(child.value.id);
            }
            above = step;
        }
        return [...selected.filter((id) => id !== parent.value.id), ...added];
    }
    const covered = new Set(descendantIds(node));
    return [...selected.filter((id) => !covered.has(id)), node.value.id];
}

/** Every node of `tree` whose folded label holds the folded `query`, by label, each with its path. */
export function flatten(tree: readonly TreeNode[], query: string): FlatEntry[] {
    const index = indexOf(tree);
    const needle = foldText(query.trim());
    return [...index.values()]
        .map(({ node }) => node)
        .filter(
            (node) =>
                !needle || foldText(node.value.label.value).includes(needle),
        )
        .sort(byLabel)
        .map((node) => ({
            node,
            path: ancestorsOf(node.value.id, tree)
                .map((id) => index.get(id)?.node.value.label.value ?? id)
                .join(PATH_SEPARATOR),
        }));
}

/** What `FacetTree` gives the rows it draws (`FacetTreeNode`). */
export interface FacetTreeContext {
    isOpen: (node: TreeNode) => boolean;
    toggleOpen: (node: TreeNode) => void;
    stateOf: (node: TreeNode) => NodeState;
    change: (node: TreeNode) => void;
    listId: (node: TreeNode) => string;
    countTitle: (value: FacetValue) => string | undefined;
    expanderLabel: (node: TreeNode) => string;
}

export const FACET_TREE_KEY: InjectionKey<FacetTreeContext> =
    Symbol("facet-tree");
