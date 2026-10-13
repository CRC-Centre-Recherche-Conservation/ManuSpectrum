import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, ref } from "vue";
import { flushPromises } from "@vue/test-utils";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    eventsQuery,
    exportHref,
    useEvents,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useEvents.ts";
import { DEBOUNCE_MS } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import { emptyFilters } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { eventsResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { EffectScope } from "vue";
import type { Filters } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (route: string) => `/en/${route}`,
}));

let fetchMock: ReturnType<typeof vi.fn>;
let scope: EffectScope;

beforeEach(() => {
    vi.useFakeTimers();
    forgetPayloads();
    fetchMock = vi.fn(async () => jsonResponse(eventsResponse()));
    vi.stubGlobal("fetch", fetchMock);
    scope = effectScope();
});

afterEach(() => {
    scope.stop();
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

describe("eventsQuery", () => {
    it("carries the filters and the sorted event types, never grain or page", () => {
        const filters: Filters = {
            ...emptyFilters(),
            q: "lead",
            grain: "analyses",
            eventType: ["production", "alteration"],
        };
        const query = eventsQuery(filters);
        expect(query.get("q")).toBe("lead");
        expect(query.getAll("eventType")).toEqual(["alteration", "production"]);
        for (const key of ["grain", "page", "size"]) {
            expect(query.has(key)).toBe(false);
        }
    });

    it("sends no event type when none is chosen: the server default applies", () => {
        expect(eventsQuery(emptyFilters()).has("eventType")).toBe(false);
    });
});

describe("exportHref", () => {
    it("names the route, the filters and the language", () => {
        const href = exportHref(
            "manuspectrum:explorer-events-csv",
            { ...emptyFilters(), q: "lead" },
            "fr",
        );
        expect(href).toBe(
            "/en/manuspectrum:explorer-events-csv?q=lead&lang=fr",
        );
    });
});

describe("useEvents", () => {
    it("is idle on null", async () => {
        const events = scope.run(() => useEvents(() => null))!;
        await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
        await flushPromises();
        expect(fetchMock).not.toHaveBeenCalled();
        expect(events.status.value).toBe("idle");
    });

    it("fetches the events route and keeps the last payload while loading", async () => {
        const filters = ref<Filters>(emptyFilters());
        const events = scope.run(() => useEvents(() => filters.value))!;
        await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
        await flushPromises();
        expect(String(fetchMock.mock.calls[0][0])).toMatch(
            /^\/en\/manuspectrum:explorer-events/,
        );
        const first = events.data.value;
        expect(first).not.toBeNull();

        fetchMock.mockImplementation(() => new Promise(() => {}));
        filters.value = { ...emptyFilters(), q: "gold" };
        await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
        await flushPromises();
        expect(String(fetchMock.mock.calls[1][0])).toContain("q=gold");
        expect(events.status.value).toBe("loading");
        expect(events.data.value).toBe(first);
    });
});
