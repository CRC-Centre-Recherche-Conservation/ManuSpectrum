import { describe, expect, it } from "vitest";

import {
    ancestorsOf,
    buildTree,
    flatten,
    nodeState,
    toggle,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/facet-tree.ts";

import { facetValue } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const VALUES = [
    facetValue("europe", "Europe"),
    facetValue("france", "France (nord)", { parent: "europe" }),
    facetValue("paris", "Paris", { parent: "france" }),
    facetValue("lille", "Lille", { parent: "france" }),
    facetValue("italy", "Italie", { parent: "europe" }),
    facetValue("lost", "Ailleurs", { parent: "unknown" }),
];

function sorted(ids: string[]): string[] {
    return [...ids].sort();
}

describe("buildTree", () => {
    it("makes a root of a value with no parent or an unknown parent, children by folded label", () => {
        const tree = buildTree(VALUES);
        expect(tree.map((node) => node.value.id)).toEqual(["lost", "europe"]);
        const europe = tree[1];
        expect(europe.children.map((node) => node.value.id)).toEqual([
            "france",
            "italy",
        ]);
        expect(europe.children[0].children.map((n) => n.value.id)).toEqual([
            "lille",
            "paris",
        ]);
    });

    it("survives a cycle by dropping it from the roots", () => {
        const tree = buildTree([
            facetValue("a", "A", { parent: "b" }),
            facetValue("b", "B", { parent: "a" }),
        ]);
        expect(tree).toEqual([]);
    });
});

describe("ancestorsOf", () => {
    it("lists the ancestors nearest first, none for a root or an unknown id", () => {
        const tree = buildTree(VALUES);
        expect(ancestorsOf("paris", tree)).toEqual(["france", "europe"]);
        expect(ancestorsOf("europe", tree)).toEqual([]);
        expect(ancestorsOf("nope", tree)).toEqual([]);
    });
});

describe("nodeState", () => {
    const tree = buildTree(VALUES);
    const node = (id: string) => {
        const find = (nodes: typeof tree): (typeof tree)[number] | null => {
            for (const entry of nodes) {
                if (entry.value.id === id) return entry;
                const inside = find(entry.children);
                if (inside) return inside;
            }
            return null;
        };
        return find(tree)!;
    };

    it("is checked for a ticked node", () => {
        expect(nodeState(node("france"), ["france"], tree)).toBe("checked");
    });

    it("is implicit under a ticked ancestor", () => {
        expect(nodeState(node("paris"), ["europe"], tree)).toBe("implicit");
    });

    it("is mixed above a ticked descendant", () => {
        expect(nodeState(node("europe"), ["paris"], tree)).toBe("mixed");
    });

    it("is none otherwise", () => {
        expect(nodeState(node("italy"), ["paris"], tree)).toBe("none");
    });
});

describe("toggle", () => {
    const tree = buildTree(VALUES);
    const node = (id: string) => {
        const find = (nodes: typeof tree): (typeof tree)[number] | null => {
            for (const entry of nodes) {
                if (entry.value.id === id) return entry;
                const inside = find(entry.children);
                if (inside) return inside;
            }
            return null;
        };
        return find(tree)!;
    };

    it("ticks an unticked node", () => {
        expect(toggle(node("paris"), [], tree)).toEqual(["paris"]);
    });

    it("ticking a node drops its ticked descendants", () => {
        expect(
            sorted(toggle(node("europe"), ["paris", "italy", "lost"], tree)),
        ).toEqual(["europe", "lost"]);
    });

    it("ticking a mixed node ticks it and drops the descendants", () => {
        expect(toggle(node("france"), ["paris"], tree)).toEqual(["france"]);
    });

    it("unticks a ticked node", () => {
        expect(
            sorted(toggle(node("france"), ["france", "lost"], tree)),
        ).toEqual(["lost"]);
    });

    it("unticking an implicit child replaces the parent by its other children", () => {
        expect(sorted(toggle(node("paris"), ["france"], tree))).toEqual([
            "lille",
        ]);
    });

    it("unticking an implicit grandchild replaces the ancestor by the siblings along the path", () => {
        expect(sorted(toggle(node("paris"), ["europe"], tree))).toEqual([
            "italy",
            "lille",
        ]);
    });

    it("leaves the ticks outside the ticked ancestor alone", () => {
        expect(sorted(toggle(node("lille"), ["europe", "lost"], tree))).toEqual(
            ["italy", "lost", "paris"],
        );
    });

    it("unticking the only child of a ticked parent leaves just the rest", () => {
        const single = buildTree([
            facetValue("a", "A"),
            facetValue("b", "B", { parent: "a" }),
        ]);
        expect(toggle(single[0].children[0], ["a"], single)).toEqual([]);
    });
});

describe("flatten", () => {
    const tree = buildTree(VALUES);

    it("lists every node with the path of its ancestors, nearest first", () => {
        const entries = flatten(tree, "");
        const paris = entries.find((entry) => entry.node.value.id === "paris")!;
        expect(paris.path).toBe("France (nord) — Europe");
        expect(entries.find((e) => e.node.value.id === "europe")!.path).toBe(
            "",
        );
    });

    it("keeps the nodes whose folded label holds the folded query, in label order", () => {
        expect(flatten(tree, "ITAL").map((e) => e.node.value.id)).toEqual([
            "italy",
        ]);
        expect(flatten(tree, "par").map((e) => e.node.value.id)).toEqual([
            "paris",
        ]);
    });

    it("gives an empty path to a node whose parent is unknown", () => {
        expect(flatten(tree, "ailleurs").map((entry) => entry.path)).toEqual([
            "",
        ]);
    });
});
