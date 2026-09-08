// Live-figures spec: the page ships server-rendered numbers as a no-JS
// fallback; conceptual-model.js must upgrade them from /api/model-graph and
// leave them UNTOUCHED when the fetch fails — a wrong number on this page is
// worse than a stale one (it once published "84 relationships" for weeks).

import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("utils/ms-nav", () => ({ default: () => {} }));

const STATS = {
    nodes: 452,
    thesaurus_nodes: 187,
    thesaurus_pct: 41,
    cidoc_classes: 44,
    relations: 70,
    models: 12,
    concepts: 19972,
    nodegroups: 169,
    total_nodes: 464,
    properties: 38,
    thesauri: 12,
};

const PAGE = `
<div class="ms-cm-stats" id="ms-cm-stats" data-api="/api/model-graph">
    <div data-stat="thesaurus"><span class="ms-cm-stat-value" data-count="40" data-suffix="%">40%</span><span class="ms-cm-stat-label">old label</span></div>
    <div data-stat="cidoc"><span class="ms-cm-stat-value" data-count="40">40</span><span class="ms-cm-stat-label"></span></div>
    <div data-stat="relations"><span class="ms-cm-stat-value" data-count="60">60</span><span class="ms-cm-stat-label"></span></div>
    <div data-stat="concepts"><span class="ms-cm-stat-value" data-count="19000" data-prefix="~">~19000</span><span class="ms-cm-stat-label"></span></div>
</div>
<p id="ms-cm-models-line">12 independent models…</p>
<p id="ms-cm-technical-line">old technical line</p>`;

async function boot(fetchImpl) {
    document.body.innerHTML = PAGE;
    document.documentElement.lang = "en";
    window.matchMedia = vi.fn().mockReturnValue({ matches: true }); // reduced motion → countUp writes immediately
    globalThis.IntersectionObserver = class {
        observe() {}
        unobserve() {}
        disconnect() {}
    };
    globalThis.fetch = fetchImpl;
    vi.resetModules();
    await import("./conceptual-model");
    document.dispatchEvent(new Event("DOMContentLoaded"));
    await new Promise((r) => setTimeout(r, 0));
}

beforeEach(() => vi.restoreAllMocks());

describe("live figures", () => {
    it("upgrades every tile and derived sentence from the payload", async () => {
        await boot(
            vi
                .fn()
                .mockResolvedValue({
                    ok: true,
                    json: async () => ({ stats: STATS }),
                }),
        );
        const value = (stat) =>
            document.querySelector(`[data-stat="${stat}"] .ms-cm-stat-value`);
        expect(value("thesaurus").textContent).toBe("41%");
        expect(value("cidoc").textContent).toBe("44");
        expect(value("relations").textContent).toBe("70");
        // prefix survives the count-up and grouping follows the page language
        expect(value("concepts").textContent).toBe("~19,972");
        expect(
            document.getElementById("ms-cm-models-line").textContent,
        ).toContain("12");
        expect(
            document.getElementById("ms-cm-models-line").textContent,
        ).toContain("70");
        expect(
            document.getElementById("ms-cm-technical-line").textContent,
        ).toContain("169");
    });

    it("keeps the server-rendered fallback when the API fails", async () => {
        await boot(vi.fn().mockResolvedValue({ ok: false }));
        expect(
            document.querySelector('[data-stat="thesaurus"] .ms-cm-stat-value')
                .textContent,
        ).toBe("40%");
        expect(
            document.getElementById("ms-cm-technical-line").textContent,
        ).toBe("old technical line");
    });

    it("keeps the fallback when the network throws", async () => {
        await boot(vi.fn().mockRejectedValue(new TypeError("offline")));
        expect(
            document.querySelector('[data-stat="relations"] .ms-cm-stat-value')
                .textContent,
        ).toBe("60");
    });
});
