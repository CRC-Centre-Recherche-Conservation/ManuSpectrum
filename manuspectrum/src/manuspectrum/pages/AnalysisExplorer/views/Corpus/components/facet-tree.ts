import type { InjectionKey } from "vue";

import { foldText } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";

import type {
    FacetKey,
    FacetValue,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

export interface TreeNode {
    value: FacetValue;
    children: TreeNode[];
    /** The ids from the root to this occurrence, joined by `KEY_SEPARATOR`. */
    key: string;
}

export type NodeState = "checked" | "implicit" | "mixed" | "none";

export interface FlatEntry {
    value: FacetValue;
    /**
     * One per distinct chain above the value: the ancestors' labels from the
     * root down to its parent, joined by « — »; `""` for a root.
     */
    paths: string[];
}

/** Facets with more values than this offer a search box. */
export const SEARCH_THRESHOLD = 8;
const PATH_SEPARATOR = " — ";
/** U+001F (unit separator): a control character no uri or id holds. */
export const KEY_SEPARATOR = "\u001f";

/** The parents present and the children of each value of one `values` list. */
export interface TreeIndex {
    parents: Map<string, FacetValue[]>;
    children: Map<string, FacetValue[]>;
}

function labelOf(value: FacetValue): string {
    return foldText(value.label.value);
}

function byValueLabel(a: FacetValue, b: FacetValue): number {
    const left = labelOf(a);
    const right = labelOf(b);
    return left < right ? -1 : left > right ? 1 : 0;
}

/** The parents of every value that are themselves among `values`. */
function presentParents(
    values: readonly FacetValue[],
): Map<string, FacetValue[]> {
    const byId = new Map(values.map((value) => [value.id, value]));
    return new Map(
        values.map((value) => [
            value.id,
            [...new Set(value.parents)]
                .filter((id) => id !== value.id)
                .flatMap((id) => byId.get(id) ?? []),
        ]),
    );
}

/** The parent and child index of `values`, to build once per list and pass to the helpers below. */
export function treeIndex(values: readonly FacetValue[]): TreeIndex {
    const parents = presentParents(values);
    return { parents, children: childrenIndex(values, parents) };
}

function childrenIndex(
    values: readonly FacetValue[],
    parents: Map<string, FacetValue[]>,
): Map<string, FacetValue[]> {
    const children = new Map<string, FacetValue[]>(
        values.map((value) => [value.id, []]),
    );
    for (const value of values) {
        for (const parent of parents.get(value.id) ?? []) {
            children.get(parent.id)?.push(value);
        }
    }
    for (const list of children.values()) list.sort(byValueLabel);
    return children;
}

/**
 * The forest of `values` by their `parents`: a value is drawn under each
 * parent present among `values`, and is a root when none is. Siblings are
 * ordered by folded label. A path never repeats an id; a value reachable only
 * through a cycle becomes a root (the first by label, then the rest).
 */
export function buildTree(
    values: readonly FacetValue[],
    index: TreeIndex = treeIndex(values),
): TreeNode[] {
    const { parents, children } = index;
    const reached = new Set<string>();

    function grow(
        value: FacetValue,
        above: readonly string[],
        prefix: string,
    ): TreeNode {
        reached.add(value.id);
        const chain = [...above, value.id];
        const key = prefix ? `${prefix}${KEY_SEPARATOR}${value.id}` : value.id;
        return {
            value,
            key,
            children: (children.get(value.id) ?? [])
                .filter((child) => !chain.includes(child.id))
                .map((child) => grow(child, chain, key)),
        };
    }

    const roots: TreeNode[] = values
        .filter((value) => !(parents.get(value.id) ?? []).length)
        .sort(byValueLabel)
        .map((value) => grow(value, [], ""));
    for (const value of [...values].sort(byValueLabel)) {
        if (!reached.has(value.id)) roots.push(grow(value, [], ""));
    }
    return roots.sort((a, b) => byValueLabel(a.value, b.value));
}

function closure(
    id: string,
    next: (id: string) => readonly FacetValue[],
): Set<string> {
    const seen = new Set<string>();
    const stack = [id];
    while (stack.length) {
        for (const value of next(stack.pop() as string)) {
            if (value.id !== id && !seen.has(value.id)) {
                seen.add(value.id);
                stack.push(value.id);
            }
        }
    }
    return seen;
}

/** Every value above `id` over all its paths, never `id` itself. */
export function ancestorIds(
    id: string,
    values: readonly FacetValue[],
    index: TreeIndex = treeIndex(values),
): Set<string> {
    return closure(id, (current) => index.parents.get(current) ?? []);
}

/** Every value below `id` over all its paths, never `id` itself. */
export function descendantIds(
    id: string,
    values: readonly FacetValue[],
    index: TreeIndex = treeIndex(values),
): Set<string> {
    return closure(id, (current) => index.children.get(current) ?? []);
}

/** The ticked ancestors of `id`, by folded label. */
export function coveringIds(
    id: string,
    selected: readonly string[],
    values: readonly FacetValue[],
    index: TreeIndex = treeIndex(values),
): string[] {
    const above = ancestorIds(id, values, index);
    return values
        .filter((value) => above.has(value.id) && selected.includes(value.id))
        .sort(byValueLabel)
        .map((value) => value.id);
}

/**
 * Ticked, covered by a ticked ancestor on any path (implicit), above a ticked
 * descendant on any path (mixed), or none of these. Every occurrence of a
 * value has the same state; ticked wins over covered.
 */
export function nodeState(
    id: string,
    selected: readonly string[],
    values: readonly FacetValue[],
    index: TreeIndex = treeIndex(values),
): NodeState {
    if (selected.includes(id)) return "checked";
    for (const above of ancestorIds(id, values, index)) {
        if (selected.includes(above)) return "implicit";
    }
    for (const below of descendantIds(id, values, index)) {
        if (selected.includes(below)) return "mixed";
    }
    return "none";
}

/**
 * The ticked ids after a click on `id`. Ticking drops the ticked descendants
 * over every path (the value already covers them); unticking a ticked value
 * removes it; a covered value cannot be clicked: the selection comes back
 * unchanged.
 */
export function toggle(
    id: string,
    selected: readonly string[],
    values: readonly FacetValue[],
    index: TreeIndex = treeIndex(values),
): string[] {
    const state = nodeState(id, selected, values, index);
    if (state === "checked") return selected.filter((item) => item !== id);
    if (state === "implicit") return [...selected];
    const covered = descendantIds(id, values, index);
    return [...selected.filter((item) => !covered.has(item)), id];
}

/** The chains above each value: labels from the root to its parent. */
function pathsOf(
    values: readonly FacetValue[],
    index: TreeIndex,
): Map<string, Set<string>> {
    const paths = new Map<string, Set<string>>();
    function visit(nodes: readonly TreeNode[], labels: readonly string[]) {
        for (const node of nodes) {
            const found = paths.get(node.value.id) ?? new Set<string>();
            found.add(labels.join(PATH_SEPARATOR));
            paths.set(node.value.id, found);
            visit(node.children, [...labels, node.value.label.value]);
        }
    }
    visit(buildTree(values, index), []);
    return paths;
}

/**
 * The values to list as search results, by label, each with its paths. With
 * `found` (the ids the server matched; null for none), those present in
 * `values`; without, the values whose folded label holds the folded `query`.
 */
export function flatten(
    values: readonly FacetValue[],
    query: string,
    found: readonly string[] | null = null,
    index: TreeIndex = treeIndex(values),
): FlatEntry[] {
    const needle = foldText(query.trim());
    const wanted = found ? new Set(found) : null;
    const paths = pathsOf(values, index);
    return values
        .filter((value) =>
            wanted
                ? wanted.has(value.id)
                : !needle || labelOf(value).includes(needle),
        )
        .sort(byValueLabel)
        .map((value) => ({
            value,
            paths: [...(paths.get(value.id) ?? [""])],
        }));
}

/**
 * A DOM-safe token for a node `key` (ids joined by `KEY_SEPARATOR`):
 * FNV-1a over its UTF-16 units, in base 36. Two occurrences of one value get
 * two tokens, since their keys differ.
 */
export function domToken(key: string): string {
    let hash = 0x811c9dc5;
    for (let index = 0; index < key.length; index++) {
        hash ^= key.charCodeAt(index);
        hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return hash.toString(36);
}

/**
 * What `FacetTree` gives the rows it draws (`FacetTreeNode`). Folding and DOM
 * ids go by occurrence (`TreeNode.key`), the state and the ticks by value id.
 */
export interface FacetTreeContext {
    facetKey: FacetKey;
    isOpen: (node: TreeNode) => boolean;
    toggleOpen: (node: TreeNode) => void;
    stateOf: (id: string) => NodeState;
    /** « covered by X and Y » for a covered value, else "". */
    coveredText: (id: string) => string;
    change: (id: string) => void;
    /** The DOM id prefix of one occurrence. */
    nodeId: (node: TreeNode) => string;
    countTitle: (value: FacetValue) => string | undefined;
    expanderLabel: (node: TreeNode) => string;
}

export const FACET_TREE_KEY: InjectionKey<FacetTreeContext> =
    Symbol("facet-tree");
