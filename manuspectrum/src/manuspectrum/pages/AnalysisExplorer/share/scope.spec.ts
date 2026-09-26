import { describe, expect, it } from "vitest";

import {
    offeredScopes,
    shareQuery,
} from "@/manuspectrum/pages/AnalysisExplorer/share/scope.ts";
import { emptyFilters } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { uuid } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { ScopeState } from "@/manuspectrum/pages/AnalysisExplorer/share/scope.ts";

const DOCUMENT = uuid(1);
const PROJECT = uuid(7);
const KEY_B = `an:${uuid(102)}:-`;
const KEY_A = `an:${uuid(101)}:-`;

function state(overrides: Partial<ScopeState> = {}): ScopeState {
    return {
        view: "corpus",
        screen: "home",
        document: null,
        basket: [],
        filters: emptyFilters(),
        ...overrides,
    };
}

const basket = [
    { key: KEY_B, kind: "analysis" as const, slot: 0 },
    { key: KEY_A, kind: "analysis" as const, slot: 1 },
];

describe("offeredScopes", () => {
    it("offers nothing on the home without a Selection", () => {
        expect(offeredScopes(state())).toEqual([]);
    });

    it("offers the document when a document is open", () => {
        expect(
            offeredScopes(
                state({
                    screen: "document",
                    document: { id: DOCUMENT, canvas: null },
                }),
            ),
        ).toEqual([{ kind: "document", id: DOCUMENT }]);
    });

    it("offers the Selection when it holds items", () => {
        expect(offeredScopes(state({ basket }))).toEqual([
            { kind: "ids", keys: [KEY_A, KEY_B] },
        ]);
    });

    it("offers both, document first", () => {
        const kinds = offeredScopes(
            state({
                screen: "document",
                document: { id: DOCUMENT, canvas: null },
                basket,
            }),
        ).map((scope) => scope.kind);
        expect(kinds).toEqual(["document", "ids"]);
    });

    it("offers a project filtered alone", () => {
        expect(
            offeredScopes(
                state({
                    screen: "results",
                    filters: { ...emptyFilters(), project: [PROJECT] },
                }),
            ),
        ).toEqual([{ kind: "project", id: PROJECT }]);
    });

    it("does not offer a project with another filter", () => {
        for (const filters of [
            { ...emptyFilters(), project: [PROJECT], q: "lead" },
            { ...emptyFilters(), project: [PROJECT], year: [2023] },
            { ...emptyFilters(), project: [PROJECT, uuid(8)] },
        ]) {
            expect(
                offeredScopes(state({ screen: "results", filters })),
            ).toEqual([]);
        }
    });

    it("does not offer a project off the results screen", () => {
        expect(
            offeredScopes(
                state({
                    screen: "home",
                    filters: { ...emptyFilters(), project: [PROJECT] },
                }),
            ),
        ).toEqual([]);
    });
});

describe("shareQuery", () => {
    it("sorts the keys in the query", () => {
        expect(
            shareQuery({ kind: "ids", keys: [KEY_B, KEY_A] }).toString(),
        ).toBe(
            new URLSearchParams([
                ["ids", KEY_A],
                ["ids", KEY_B],
            ]).toString(),
        );
    });

    it("names a document or a project", () => {
        expect(shareQuery({ kind: "document", id: DOCUMENT }).toString()).toBe(
            `document=${DOCUMENT}`,
        );
        expect(shareQuery({ kind: "project", id: PROJECT }).toString()).toBe(
            `project=${PROJECT}`,
        );
    });
});
