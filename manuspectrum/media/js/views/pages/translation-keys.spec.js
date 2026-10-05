import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const here = path.dirname(new URL(import.meta.url).pathname);
const template = fs.readFileSync(
    path.join(here, "../../../../templates/javascript.htm"),
    "utf-8",
);

// Same rule as arches.js `convertToCamelCase`: a digit after a dash stays as is.
const defined = new Set(
    [...template.matchAll(/^\s+([a-z0-9-]+)='/gm)].map(([, name]) =>
        name.replace(/-([a-z])/g, (m, c) => c.toUpperCase()),
    ),
);

describe.each(["contact", "conceptual-model", "graph-explorer"])(
    "%s translation keys",
    (page) => {
        it("are all defined in templates/javascript.htm", () => {
            const source = fs.readFileSync(path.join(here, `${page}.js`), "utf-8");
            const keys = [
                ...source.matchAll(/\b(?:t|tv|trv)\(\s*"([A-Za-z0-9]+)"/g),
            ].map(([, key]) => key);

            expect(keys.length).toBeGreaterThan(0);
            expect(keys.filter((key) => !defined.has(key))).toEqual([]);
        });
    },
);
