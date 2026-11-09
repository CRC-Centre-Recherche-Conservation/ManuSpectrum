/**
 * Vitest unit spec — the report block of the project's
 * templates/views/components/widgets/reference-select.htm (issue #294).
 *
 * In the running app this block is bound to the view model of
 * arches-controlled-lists, never to a project one:
 * utils/load-component-dependencies.js tries the arches applications in
 * INSTALLED_APPS order, and arches-controlled-lists provides
 * views/components/widgets/reference-select.js before the project could. So
 * the block is bound here to a stand-in that has only what that view model
 * offers the report (value, label, nodeCssClasses, getPrefLabel) plus the
 * page's `translations`, and nothing of the project's.
 *
 * Vitest stubs `templates/*.htm` imports, so the block is read from disk and
 * bound with the real Knockout in jsdom, as ms-summary-popup.spec.js does.
 * The arches-controlled-lists block is bound the same way: it shows the bug
 * the project block exists for.
 *
 * Note: this file lives under media/js/views/components/, which coverage.include
 * does not target, so it executes without touching the coverage gate.
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

import { afterEach, describe, expect, it } from "vitest";
import ko from "knockout";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..", "..", "..", "..", "..", "..");
const TEMPLATE = path.join(
    "views",
    "components",
    "widgets",
    "reference-select.htm",
);
const PROJECT_TEMPLATE = path.join(ROOT, "manuspectrum", "templates", TEMPLATE);
const UPSTREAM_TEMPLATE = path.join(
    ROOT,
    "node_modules",
    "arches_controlled_lists",
    "arches_controlled_lists",
    "templates",
    TEMPLATE,
);

const FORS =
    "https://ark.notre-dame.science/ark:/35572/ndpnf4ww5qcbn0h5b67ctmt";
const AAT = "http://vocab.getty.edu/aat/300053228";

const reportBlock = (file) => {
    const match = fs
        .readFileSync(file, "utf-8")
        .match(/\{% block report %\}([\s\S]*?)\{% endblock report %\}/);
    if (!match) {
        throw new Error(`no report block in ${file}`);
    }
    return match[1];
};

/** What the report reads off the arches-controlled-lists view model, and no more. */
function UpstreamReportSurface(value) {
    this.value = value;
    this.label = "Technique";
    this.nodeCssClasses = "node";
    this.getPrefLabel = (labels) =>
        ko.toJS(labels)?.find((label) => label.valuetype_id === "prefLabel")
            ?.value || "unlabeled";
    // The page view model's, reached as $root in the report.
    this.translations = { none: "None" };
}

const reference = (uri, label = "FORS") => ({
    uri,
    labels: [{ value: label, valuetype_id: "prefLabel", language_id: "en" }],
    list_id: "12dc9a7b-b177-450a-a927-711fa7882882",
});

let mounted = [];

const render = (references, file = PROJECT_TEMPLATE) => {
    const root = document.createElement("dl");
    root.innerHTML = reportBlock(file);
    document.body.appendChild(root);
    mounted.push(root);
    ko.applyBindings(
        new UpstreamReportSurface(ko.observable(references)),
        root,
    );
    return root;
};

const items = (root) => [...root.querySelectorAll("dd")];

afterEach(() => {
    mounted.forEach((root) => {
        ko.cleanNode(root);
        root.remove();
    });
    mounted = [];
});

describe("reference-select report block", () => {
    it("links a reference whose URI is an http(s) URL, in a new tab", () => {
        const root = render([reference(FORS)]);
        const links = root.querySelectorAll("a");
        expect(links).toHaveLength(1);
        expect(links[0].getAttribute("href")).toBe(FORS);
        expect(links[0].getAttribute("target")).toBe("_blank");
        expect(links[0].getAttribute("rel")).toBe("noopener noreferrer");
        expect(links[0].textContent).toBe("FORS");
    });

    it("shows the label of a bare-id reference without any link", () => {
        const root = render([reference("61296")]);
        expect(root.querySelector("a")).toBeNull();
        expect(root.querySelector("[href]")).toBeNull();
        expect(root.querySelector("dd span").textContent).toBe("FORS");
    });

    it("decides for each reference of a multi-value node", () => {
        const root = render([
            reference(FORS),
            reference("61042", "Sampling"),
            reference(AAT, "Microscopy"),
        ]);
        expect(items(root).map((item) => item.textContent.trim())).toEqual([
            "FORS",
            "Sampling",
            "Microscopy",
        ]);
        expect(
            items(root).map(
                (item) => item.querySelector("a")?.getAttribute("href") ?? null,
            ),
        ).toEqual([FORS, null, AAT]);
    });

    it("reads a URI held in an observable, as mapped tile data holds it", () => {
        const root = render([
            reference(ko.observable(FORS)),
            reference(ko.observable("61042"), "Sampling"),
        ]);
        expect(items(root)[0].querySelector("a").getAttribute("href")).toBe(
            FORS,
        );
        expect(items(root)[1].querySelector("a")).toBeNull();
        expect(items(root)[1].textContent.trim()).toBe("Sampling");
    });

    it("trims the whitespace around a URI", () => {
        const root = render([reference(`  ${FORS}\n`)]);
        expect(root.querySelector("a").getAttribute("href")).toBe(FORS);
    });

    it("never links a relative, hostless, script or other non-http(s) URI", () => {
        for (const uri of [
            "report/61296",
            "/fr/report/61296",
            "//example.org/x",
            "https://",
            "https:///path",
            "http:example.org",
            "javascript:alert(1)",
            "data:text/html,x",
            "mailto:someone@example.org",
            "ftp://example.org/x",
            "",
            "   ",
            null,
            61296,
        ]) {
            const root = render([reference(uri)]);
            expect(root.querySelector("a"), String(uri)).toBeNull();
            expect(root.querySelector("dd span").textContent, String(uri)).toBe(
                "FORS",
            );
        }
    });

    it("shows the label of a reference that has no URI at all", () => {
        const { uri: _uri, ...withoutUri } = reference(FORS);
        const root = render([withoutUri]);
        expect(root.querySelector("a")).toBeNull();
        expect(root.querySelector("dd span").textContent).toBe("FORS");
    });

    it("keeps the empty state of the original block", () => {
        const root = render(null);
        expect(items(root)).toHaveLength(1);
        expect(root.querySelector("dd span").textContent).toBe("None");
    });

    it("reads from the view model only what the arches-controlled-lists block reads", () => {
        const names = (file) =>
            new Set(
                [
                    ...reportBlock(file).matchAll(/\$(?:parent|root)\.(\w+)/g),
                ].map((m) => m[1]),
            );
        const upstream = names(UPSTREAM_TEMPLATE);
        expect(
            [...names(PROJECT_TEMPLATE)].filter((name) => !upstream.has(name)),
        ).toEqual([]);
    });

    it("replaces an arches-controlled-lists block that links a bare id relative to the report page", () => {
        const root = render([reference("61296")], UPSTREAM_TEMPLATE);
        expect(root.querySelector("a").getAttribute("href")).toBe("61296");
    });

    it("extends the arches-controlled-lists template and replaces its report block only", () => {
        const text = fs.readFileSync(PROJECT_TEMPLATE, "utf-8");
        expect(
            text.startsWith(
                '{% extends "views/components/widgets/reference-select.htm" %}',
            ),
        ).toBe(true);
        expect(text.match(/\{% block (\w+) %\}/g)).toEqual([
            "{% block report %}",
        ]);
    });
});
