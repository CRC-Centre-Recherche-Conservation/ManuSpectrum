import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useSelectionItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionItems.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisHit,
    fileEntry,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { EffectScope } from "vue";
import type { Item } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { SelectionItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionItems.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: () => "/en/api/explorer/items",
}));

function whole(n: number): Item {
    const analysis = analysisHit(n);
    return {
        key: `an:${analysis.id}:-`,
        kind: "analysis",
        analysis,
        files: [fileEntry()],
    };
}

const FIRST = whole(1);
const SECOND = whole(2);

let visible: Set<string>;
let fetchMock: ReturnType<typeof vi.fn>;
let scope: EffectScope;

function requested(call: number): string[] {
    const url = String(fetchMock.mock.calls[call][0]);
    return new URLSearchParams(url.split("?")[1]).getAll("ids");
}

function start(): SelectionItems {
    scope = effectScope();
    return scope.run(() => useSelectionItems())!;
}

beforeEach(() => {
    forgetPayloads();
    setActivePinia(createPinia());
    visible = new Set();
    fetchMock = vi.fn(async (url: string) => {
        const keys = new URLSearchParams(url.split("?")[1]).getAll("ids");
        const items = [FIRST, SECOND].filter(
            (item) => keys.includes(item.key) && visible.has(item.key),
        );
        return jsonResponse({
            items,
            missing: keys.filter((key) => !visible.has(key)),
        });
    });
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
    scope.stop();
    vi.unstubAllGlobals();
});

describe("useSelectionItems", () => {
    it("reads a missing key again when the Selection changes, and clears it once it is read", async () => {
        useExplorerStore().addManyToBasket([FIRST.key]);
        const selection = start();
        await flushPromises();
        expect([...selection.missing.value]).toEqual([FIRST.key]);
        visible.add(FIRST.key).add(SECOND.key);
        useExplorerStore().addManyToBasket([SECOND.key]);
        await flushPromises();
        expect(requested(1).sort()).toEqual([FIRST.key, SECOND.key].sort());
        expect(selection.missing.value.size).toBe(0);
        expect([...selection.byKey.value.keys()].sort()).toEqual(
            [FIRST.key, SECOND.key].sort(),
        );
        expect(selection.settled.value).toBe(true);
    });

    it("reads the missing keys again, from the server, on retry", async () => {
        useExplorerStore().addManyToBasket([FIRST.key]);
        const selection = start();
        await flushPromises();
        visible.add(FIRST.key);
        selection.retry();
        await flushPromises();
        expect(fetchMock).toHaveBeenCalledTimes(2);
        expect(requested(1)).toEqual([FIRST.key]);
        expect(selection.missing.value.size).toBe(0);
        expect(selection.byKey.value.get(FIRST.key)).toEqual(FIRST);
    });

    it("keeps a key missing while the items API still reports it", async () => {
        useExplorerStore().addManyToBasket([FIRST.key]);
        const selection = start();
        await flushPromises();
        visible.add(SECOND.key);
        useExplorerStore().addManyToBasket([SECOND.key]);
        await flushPromises();
        expect([...selection.missing.value]).toEqual([FIRST.key]);
        expect(selection.byKey.value.has(SECOND.key)).toBe(true);
    });
});
