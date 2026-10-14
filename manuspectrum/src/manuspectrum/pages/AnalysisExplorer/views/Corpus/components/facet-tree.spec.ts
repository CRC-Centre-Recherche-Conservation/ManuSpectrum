import { describe, expect, it } from "vitest";

import {
    ancestorIds,
    buildTree,
    coveringIds,
    descendantIds,
    domToken,
    flatten,
    KEY_SEPARATOR,
    nodeState,
    toggle,
    treeIndex,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/facet-tree.ts";

import { facetValue } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { TreeNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/facet-tree.ts";

const PLACES = [
    facetValue("europe", "Europe"),
    facetValue("france", "France (nord)", { parents: ["europe"] }),
    facetValue("paris", "Paris", { parents: ["france"] }),
    facetValue("lille", "Lille", { parents: ["france"] }),
    facetValue("italy", "Italie", { parents: ["europe"] }),
    facetValue("lost", "Ailleurs", { parents: ["unknown"] }),
];

/** Pigments: lapis sits under two parents; `blue` is under `pigment`. */
const TERMS = [
    facetValue("pigment", "Pigment"),
    facetValue("mineral", "Mineral"),
    facetValue("blue", "Blue pigment", { parents: ["pigment"] }),
    facetValue("lapis", "Lapis lazuli", { parents: ["blue", "mineral"] }),
    facetValue("azurite", "Azurite", { parents: ["blue"] }),
];

function sorted(ids: string[]): string[] {
    return [...ids].sort();
}

function ids(nodes: readonly TreeNode[]): string[] {
    return nodes.map((node) => node.value.id);
}

function occurrences(nodes: readonly TreeNode[], id: string): TreeNode[] {
    return nodes.flatMap((node) => [
        ...(node.value.id === id ? [node] : []),
        ...occurrences(node.children, id),
    ]);
}

describe("buildTree", () => {
    it("makes a root of a value whose parents are absent, children by folded label", () => {
        const tree = buildTree(PLACES);
        expect(ids(tree)).toEqual(["lost", "europe"]);
        expect(ids(tree[1].children)).toEqual(["france", "italy"]);
        expect(ids(tree[1].children[0].children)).toEqual(["lille", "paris"]);
    });

    it("draws a value under each parent present", () => {
        const tree = buildTree(TERMS);
        expect(occurrences(tree, "lapis")).toHaveLength(2);
        const keys = occurrences(tree, "lapis").map((node) => node.key);
        expect(sorted(keys)).toEqual(
            [
                ["mineral", "lapis"],
                ["pigment", "blue", "lapis"],
            ].map((chain) => chain.join(KEY_SEPARATOR)),
        );
        expect(ids(tree)).toEqual(["mineral", "pigment"]);
    });

    it("ignores a parent that is absent and keeps the present one", () => {
        const tree = buildTree([
            facetValue("a", "A"),
            facetValue("b", "B", { parents: ["gone", "a"] }),
        ]);
        expect(ids(tree)).toEqual(["a"]);
        expect(ids(tree[0].children)).toEqual(["b"]);
    });

    it("makes a root of a value whose parents are all absent", () => {
        const tree = buildTree([
            facetValue("a", "A", { parents: ["gone", "also-gone"] }),
        ]);
        expect(ids(tree)).toEqual(["a"]);
        expect(tree[0].key).toBe("a");
    });

    it("never loops on a cycle and keeps its values reachable", () => {
        const tree = buildTree([
            facetValue("a", "A", { parents: ["b"] }),
            facetValue("b", "B", { parents: ["a"] }),
        ]);
        expect(ids(tree)).toEqual(["a"]);
        expect(ids(tree[0].children)).toEqual(["b"]);
        expect(tree[0].children[0].children).toEqual([]);
    });

    it("orders siblings by folded label, not by input order", () => {
        const tree = buildTree([
            facetValue("z", "Zinc"),
            facetValue("e", "Étain"),
            facetValue("a", "azurite"),
        ]);
        expect(ids(tree)).toEqual(["a", "e", "z"]);
    });
});

describe("node keys", () => {
    it("never confuse a uri root with a path whose ids join into the same text", () => {
        const tree = buildTree([
            facetValue("http://a/b", "Root with a slash"),
            facetValue("http://a", "Parent"),
            facetValue("b", "Child", { parents: ["http://a"] }),
        ]);
        const keys = [
            ...occurrences(tree, "http://a/b"),
            ...occurrences(tree, "b"),
        ].map((node) => node.key);

        expect(new Set(keys).size).toBe(2);
    });
});

describe("treeIndex", () => {
    it("is what the helpers read when one is given", () => {
        const index = treeIndex(TERMS);
        const flat = TERMS.map((value) => ({ ...value, parents: [] }));

        expect(nodeState("azurite", ["pigment"], flat, index)).toBe("implicit");
        expect(sorted([...ancestorIds("lapis", flat, index)])).toEqual(
            sorted(["blue", "mineral", "pigment"]),
        );
        expect(toggle("pigment", ["azurite"], flat, index)).toEqual([
            "pigment",
        ]);
        expect(ids(buildTree(flat, index))).toEqual(["mineral", "pigment"]);
    });
});

describe("ancestorIds and descendantIds", () => {
    it("close over every path, never include the value, survive a cycle", () => {
        expect(sorted([...ancestorIds("lapis", TERMS)])).toEqual([
            "blue",
            "mineral",
            "pigment",
        ]);
        expect([...ancestorIds("pigment", TERMS)]).toEqual([]);
        expect([...ancestorIds("nope", TERMS)]).toEqual([]);
        expect(sorted([...descendantIds("pigment", TERMS)])).toEqual([
            "azurite",
            "blue",
            "lapis",
        ]);
        const loop = [
            facetValue("a", "A", { parents: ["b"] }),
            facetValue("b", "B", { parents: ["a"] }),
        ];
        expect([...ancestorIds("a", loop)]).toEqual(["b"]);
        expect([...descendantIds("a", loop)]).toEqual(["b"]);
    });
});

describe("coveringIds", () => {
    it("lists the ticked ancestors over every path, by folded label", () => {
        expect(
            coveringIds("lapis", ["pigment", "mineral", "azurite"], TERMS),
        ).toEqual(["mineral", "pigment"]);
        expect(coveringIds("lapis", ["lapis"], TERMS)).toEqual([]);
    });
});

describe("nodeState", () => {
    it("is checked for a ticked value", () => {
        expect(nodeState("france", ["france"], PLACES)).toBe("checked");
    });

    it("is implicit under any ticked ancestor, covering ancestors in label order", () => {
        expect(nodeState("paris", ["europe"], PLACES)).toBe("implicit");
        expect(nodeState("lapis", ["mineral"], TERMS)).toBe("implicit");
        expect(nodeState("lapis", ["pigment"], TERMS)).toBe("implicit");
    });

    it("is mixed above a ticked descendant on any path", () => {
        expect(nodeState("europe", ["paris"], PLACES)).toBe("mixed");
        expect(nodeState("mineral", ["lapis"], TERMS)).toBe("mixed");
        expect(nodeState("pigment", ["lapis"], TERMS)).toBe("mixed");
    });

    it("is none otherwise", () => {
        expect(nodeState("italy", ["paris"], PLACES)).toBe("none");
        expect(nodeState("azurite", ["mineral"], TERMS)).toBe("none");
    });

    it("reads checked for a ticked value under a ticked ancestor", () => {
        expect(nodeState("lapis", ["pigment", "lapis"], TERMS)).toBe("checked");
    });

    it("gives every occurrence of a term the same state", () => {
        const tree = buildTree(TERMS);
        const selected = ["mineral"];
        const states = occurrences(tree, "lapis").map((node) =>
            nodeState(node.value.id, selected, TERMS),
        );
        expect(states).toEqual(["implicit", "implicit"]);
    });
});

describe("toggle", () => {
    it("ticks an unticked value", () => {
        expect(toggle("paris", [], PLACES)).toEqual(["paris"]);
    });

    it("ticking drops the ticked descendants of every path", () => {
        expect(
            sorted(toggle("pigment", ["lapis", "azurite", "mineral"], TERMS)),
        ).toEqual(["mineral", "pigment"]);
        expect(
            sorted(toggle("europe", ["paris", "italy", "lost"], PLACES)),
        ).toEqual(["europe", "lost"]);
    });

    it("ticking a mixed value ticks it and drops the descendants", () => {
        expect(toggle("france", ["paris"], PLACES)).toEqual(["france"]);
    });

    it("unticks a ticked value", () => {
        expect(sorted(toggle("france", ["france", "lost"], PLACES))).toEqual([
            "lost",
        ]);
    });

    it("changes nothing on an implicit value", () => {
        const selected = ["pigment"];
        const next = toggle("lapis", selected, TERMS);
        expect(next).toEqual(["pigment"]);
        expect(next).not.toBe(selected);
    });

    it("unticking a covered place changes nothing and never ticks its siblings", () => {
        expect(toggle("paris", ["france"], PLACES)).toEqual(["france"]);
        expect(toggle("paris", ["europe"], PLACES)).toEqual(["europe"]);
    });

    it("leaves the ticks outside the ticked ancestor alone", () => {
        expect(sorted(toggle("lille", ["europe", "lost"], PLACES))).toEqual([
            "europe",
            "lost",
        ]);
    });

    it("unticks a place tree value as before", () => {
        expect(toggle("paris", ["paris"], PLACES)).toEqual([]);
    });
});

describe("flatten", () => {
    it("lists the found ids with every path", () => {
        const entries = flatten(TERMS, "ignored", ["lapis", "pigment"]);
        expect(entries.map((entry) => entry.value.id)).toEqual([
            "lapis",
            "pigment",
        ]);
        expect(sorted(entries[0].paths)).toEqual([
            "Mineral",
            "Pigment — Blue pigment",
        ]);
        expect(entries[1].paths).toEqual([""]);
    });

    it("lists nothing for an empty found and skips ids that are absent", () => {
        expect(flatten(TERMS, "", [])).toEqual([]);
        expect(
            flatten(TERMS, "", ["nope", "azurite"]).map(
                (entry) => entry.value.id,
            ),
        ).toEqual(["azurite"]);
    });

    it("filters by folded label without found", () => {
        expect(flatten(PLACES, "ITAL").map((e) => e.value.id)).toEqual([
            "italy",
        ]);
        expect(flatten(PLACES, "ITAL", null).map((e) => e.value.id)).toEqual([
            "italy",
        ]);
        const paris = flatten(PLACES, "par")[0];
        expect(paris.paths).toEqual(["Europe — France (nord)"]);
        expect(flatten(PLACES, "").map((e) => e.value.id)).toHaveLength(6);
    });

    it("gives an empty path to a value whose parent is unknown", () => {
        expect(flatten(PLACES, "ailleurs").map((e) => e.paths)).toEqual([[""]]);
    });
});

describe("domToken", () => {
    it("gives two occurrences of one value two DOM-safe tokens, the same each time", () => {
        const first = domToken("http://x.test/blue/http://x.test/azurite");
        const second = domToken("http://x.test/mineral/http://x.test/azurite");
        expect(first).not.toBe(second);
        expect(first).toMatch(/^[a-z0-9]+$/);
        expect(domToken("http://x.test/blue/http://x.test/azurite")).toBe(
            first,
        );
    });
});
