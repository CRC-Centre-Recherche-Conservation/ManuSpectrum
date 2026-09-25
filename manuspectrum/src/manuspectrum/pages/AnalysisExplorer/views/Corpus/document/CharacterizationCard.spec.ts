import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";

import CharacterizationCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/CharacterizationCard.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisPayload,
    characterization,
    fileEntry,
    label,
    uuid,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { CharacterizationSummary } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (_route: string, params: Record<string, string>) =>
        `/en/api/explorer/analysis/${params.resourceid}`,
}));

const SCALE = {
    levels: [0, 1, 2, 3].map((rank) => ({
        ...valueRef(
            `c:${rank}`,
            ["Very reliable", "Reliable", "Plausible", "Uncertain"][rank],
        ),
        rank,
    })),
};

function analysisWith(id: string, withData: boolean) {
    return analysisPayload({
        id,
        name: label(`Analysis ${id.slice(-3)}`),
        files: withData
            ? [fileEntry({ id: uuid(800 + Number(id.slice(-3))) })]
            : [],
    });
}

function mountCard(
    evidence: string[],
    responses: Record<string, unknown>,
    status = 200,
    overrides: Partial<CharacterizationSummary> = {},
) {
    vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) =>
            jsonResponse(responses[url.split("/").pop()!] ?? {}, status),
        ),
    );
    const pinia = createPinia();
    setActivePinia(pinia);
    const summary = characterization(1, {
        evidence,
        materials: [
            {
                value: valueRef("m:vermilion", "Vermilion"),
                confidence: SCALE.levels[1],
                proportion: null,
            },
        ],
        note: { html: "<p>Hg and S <em>together</em></p>", lang: "en" },
        ...overrides,
    });
    const wrapper = mount(CharacterizationCard, {
        props: { summary, scale: SCALE },
        global: { plugins: [pinia] },
    });
    return { wrapper, store: useExplorerStore(), summary };
}

afterEach(() => vi.unstubAllGlobals());

describe("CharacterizationCard", () => {
    it("writes each material with its degree of certainty in words", async () => {
        const { wrapper } = mountCard([], {});
        expect(wrapper.find(".materials").text()).toContain("Vermilion");
        expect(wrapper.find(".materials").text()).toContain("Reliable");
        expect(wrapper.find(".scale").text()).toContain("Uncertain");
        expect(wrapper.find(".note").html()).toContain("<em>together</em>");
    });

    it("lists the evidence analyses by name and opens one", async () => {
        const { wrapper, store } = mountCard([uuid(101)], {
            [uuid(101)]: analysisWith(uuid(101), true),
        });
        await flushPromises();
        const item = wrapper.find(".evidence button");
        expect(item.text()).toContain("Analysis 101");
        await item.trigger("click");
        expect(store.focus).toEqual({ kind: "analysis", id: uuid(101) });
    });

    it("adds the material and its evidence in one step", async () => {
        const { wrapper, store, summary } = mountCard([uuid(101), uuid(102)], {
            [uuid(101)]: analysisWith(uuid(101), true),
            [uuid(102)]: analysisWith(uuid(102), true),
        });
        await flushPromises();
        await wrapper.find(".with-evidence button").trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual([
            `ch:${summary.id}:-`,
            `af:${uuid(101)}:${uuid(901)}`,
            `af:${uuid(102)}:${uuid(902)}`,
        ]);
    });

    it("refuses the batch when it does not fit", async () => {
        const { wrapper, store } = mountCard([uuid(101)], {
            [uuid(101)]: analysisWith(uuid(101), true),
        });
        store.addManyToBasket(
            Array.from(
                { length: 29 },
                (_, n) => `af:${uuid(300 + n)}:${uuid(400 + n)}`,
            ),
        );
        await flushPromises();
        expect(
            wrapper.find(".with-evidence button").attributes("disabled"),
        ).toBeDefined();
        expect(store.basket).toHaveLength(29);
    });

    it("reports an evidence analysis without displayable data", async () => {
        const { wrapper, store, summary } = mountCard([uuid(101), uuid(102)], {
            [uuid(101)]: analysisWith(uuid(101), true),
            [uuid(102)]: analysisWith(uuid(102), false),
        });
        await flushPromises();
        expect(wrapper.find(".with-evidence").text()).toContain(
            "1 supporting analysis has no data to show",
        );
        await wrapper.find(".with-evidence button").trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual([
            `ch:${summary.id}:-`,
            `af:${uuid(101)}:${uuid(901)}`,
        ]);
    });

    it("adds nothing with its evidence when an analysis cannot be read, and says so", async () => {
        const { wrapper } = mountCard([uuid(101)], {}, 503);
        await flushPromises();
        expect(wrapper.find(".with-evidence button").exists()).toBe(false);
        expect(wrapper.text()).toContain(
            "The supporting analyses could not be read",
        );
        expect(wrapper.find(".alone button").exists()).toBe(true);
    });

    it("links a web source and writes an unsafe one as plain text", () => {
        const { wrapper } = mountCard([], {}, 200, {
            sources: [
                {
                    title: label("Web page"),
                    url: "https://example.org/p",
                    ref: null,
                },
                { title: label("Trap"), url: "javascript:alert(1)", ref: null },
            ],
        });
        const links = wrapper.findAll(".sources a");
        expect(links).toHaveLength(1);
        expect(links[0].attributes("href")).toBe("https://example.org/p");
        expect(wrapper.find(".sources").text()).toContain("Trap");
    });

    it("asks to be closed", async () => {
        const { wrapper } = mountCard([], {});
        await wrapper.find(".card-head .close").trigger("click");
        expect(wrapper.emitted("close")).toHaveLength(1);
    });

    it("offers no evidence of the previous material while the next one's loads", async () => {
        const { wrapper } = mountCard([uuid(101)], {
            [uuid(101)]: analysisWith(uuid(101), true),
        });
        await flushPromises();
        vi.stubGlobal(
            "fetch",
            vi.fn(() => new Promise(() => undefined)),
        );
        await wrapper.setProps({
            summary: characterization(2, { evidence: [uuid(102)] }),
        });
        await flushPromises();
        expect(wrapper.find(".with-evidence button").exists()).toBe(false);
        expect(wrapper.find(".evidence").text()).not.toContain("Analysis 101");
    });

    it("gives its section headings ids of its own", () => {
        const pinia = createPinia();
        setActivePinia(pinia);
        const summary = characterization(1);
        const wrapper = mount(
            defineComponent(() => () => [
                h(CharacterizationCard, { summary, scale: SCALE }),
                h(CharacterizationCard, { summary, scale: SCALE }),
            ]),
            { global: { plugins: [pinia] } },
        );
        const sections = wrapper.findAll(".materials");
        const ids = sections.map((section) =>
            section.find("h4").attributes("id"),
        );
        expect(ids[0]).toBeTruthy();
        expect(ids[0]).not.toBe(ids[1]);
        expect(sections[0].attributes("aria-labelledby")).toBe(ids[0]);
    });
});
