// @vitest-environment node
//
// jsdom replaces the global URL constructor; Node's fileURLToPath then
// rejects the jsdom instance it receives from `new URL(...)`. This file
// touches no DOM, so it runs under the real Node environment instead.
import fs from "fs";
import { fileURLToPath } from "url";
import { describe, expect, it } from "vitest";

import { SHAPE_KEYS } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const CONTRACT = fileURLToPath(
    new URL("../../../../../../tests/explorer_contract.py", import.meta.url),
);

function pythonShapes(source: string): Record<string, string[]> {
    const constants: Record<string, string[]> = {};
    for (const match of source.matchAll(/^([A-Z_]+) = \{([^}]*)\}/gm)) {
        constants[match[1]] = [...match[2].matchAll(/"(\w+)":/g)].map(
            (key) => key[1],
        );
    }
    const block = source.slice(source.indexOf("SHAPES = {"));
    const shapes: Record<string, string[]> = {};
    let current: string | null = null;
    for (const line of block.split("\n").slice(1)) {
        const constant = /^ {4}"(\w+)": ([A-Z_]+),$/.exec(line);
        const inline = /^ {4}"(\w+)": \{(.*)\},$/.exec(line);
        const opening = /^ {4}"(\w+)": \{$/.exec(line);
        const key = /^ {8}"(\w+)":/.exec(line);
        if (constant) {
            shapes[constant[1]] = constants[constant[2]];
        } else if (inline) {
            shapes[inline[1]] = [...inline[2].matchAll(/"(\w+)":/g)].map(
                (found) => found[1],
            );
        } else if (opening) {
            current = opening[1];
            shapes[current] = [];
        } else if (key && current) {
            shapes[current].push(key[1]);
        } else if (/^ {4}\},$/.test(line)) {
            current = null;
        } else if (/^\}$/.test(line)) {
            break;
        }
    }
    return shapes;
}

describe("api/types.ts mirrors tests/explorer_contract.py", () => {
    const shapes = pythonShapes(fs.readFileSync(CONTRACT, "utf-8"));

    it("declares the same shapes", () => {
        expect(Object.keys(SHAPE_KEYS).sort()).toEqual(
            Object.keys(shapes).sort(),
        );
    });

    it.each(Object.keys(SHAPE_KEYS))("gives %s the same keys", (name) => {
        const keys = Object.keys(
            SHAPE_KEYS[name as keyof typeof SHAPE_KEYS],
        ).sort();
        expect(keys).toEqual([...shapes[name]].sort());
    });
});
