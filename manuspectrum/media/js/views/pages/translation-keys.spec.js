import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const here = path.dirname(new URL(import.meta.url).pathname);
const templates = path.join(here, "../../../../templates");
const read = (...parts) => fs.readFileSync(path.join(...parts), "utf-8");

// Same rule as arches.js `convertToCamelCase`: a digit after a dash stays as is.
const camel = (name) => name.replace(/-([a-z])/g, (m, c) => c.toUpperCase());
const definedIn = (file) =>
    new Set(
        [...read(templates, file).matchAll(/^\s+([a-z0-9-]+)='/gm)].map(([, name]) =>
            camel(name),
        ),
    );

const PAGES = [
    ["contact", "contact", "includes/ms_i18n_contact.htm"],
    ["conceptual-model", "conceptual-model", "includes/ms_i18n_conceptual_model.htm"],
    ["graph-explorer", "graph-explorer", "includes/ms_i18n_graph_explorer.htm"],
];

describe.each(PAGES)("%s translation keys", (page, template, partial) => {
    it("are all rendered by the page's own partial", () => {
        const source = read(here, `${page}.js`);
        // Every project key literal, wherever it is passed from.
        const keys = [...new Set([...source.matchAll(/"(ms[A-Z][A-Za-z0-9]*)"/g)].map(([, key]) => key))];
        const defined = definedIn(partial);

        expect(keys.length).toBeGreaterThan(0);
        expect(keys.filter((key) => !defined.has(key))).toEqual([]);
    });

    it("are included by the page template", () => {
        expect(read(templates, "views/pages", `${template}.htm`)).toContain(
            `{% include '${partial}' %}`,
        );
    });

    it("are not left in templates/javascript.htm", () => {
        const left = definedIn("javascript.htm");
        const own = definedIn(partial);
        expect([...own].filter((key) => left.has(key))).toEqual([]);
    });
});

describe("public page base", () => {
    it("does not include javascript.htm", () => {
        expect(read(templates, "ms_base.htm")).not.toMatch(/include\s+['"]javascript\.htm['"]/);
    });

    it("the shared header carries no style block", () => {
        expect(read(templates, "includes/ms_header.htm")).not.toMatch(/<style|<noscript/);
    });

    it("the pages without a script catalogue read no translation key", () => {
        for (const page of ["team", "analysis-explorer"]) {
            expect(read(here, `${page}.js`)).not.toMatch(/utils\/i18n|arches\.translations/);
        }
    });
});
