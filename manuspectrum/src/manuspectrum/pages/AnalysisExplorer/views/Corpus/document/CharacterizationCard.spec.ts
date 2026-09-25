import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";

import CharacterizationCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/CharacterizationCard.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    characterization,
    label,
    uuid,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type {
    CharacterizationSummary,
    NamedRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const SCALE = {
    levels: [0, 1, 2, 3].map((rank) => ({
        ...valueRef(
            `c:${rank}`,
            ["Very reliable", "Reliable", "Plausible", "Uncertain"][rank],
        ),
        rank,
    })),
};

function evidenceOf(ids: string[]): NamedRef[] {
    return ids.map((id) => ({ id, name: label(`Analysis ${id.slice(-3)}`) }));
}

function mountCard(
    evidence: string[],
    overrides: Partial<CharacterizationSummary> = {},
) {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const pinia = createPinia();
    setActivePinia(pinia);
    const summary = characterization(1, {
        evidence: evidenceOf(evidence),
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
    return { wrapper, store: useExplorerStore(), summary, fetchMock };
}

afterEach(() => vi.unstubAllGlobals());

describe("CharacterizationCard", () => {
    it("writes each material with its degree of certainty in words", async () => {
        const { wrapper } = mountCard([]);
        expect(wrapper.find(".materials").text()).toContain("Vermilion");
        expect(wrapper.find(".materials").text()).toContain("Reliable");
        expect(wrapper.find(".scale").text()).toContain("Uncertain");
        expect(wrapper.find(".note").html()).toContain("<em>together</em>");
    });

    it("marks on the scale the level of this identification", () => {
        const { wrapper } = mountCard([]);
        const current = wrapper.findAll(".scale li[aria-current='true']");
        expect(current).toHaveLength(1);
        expect(current[0].text()).toContain("Reliable");
    });

    it("names an element group as the elements of its level", () => {
        const { wrapper } = mountCard([], {
            elements: [
                {
                    level: { ...valueRef("l:major", "major"), rank: 0 },
                    values: [valueRef("e:pb", "Pb")],
                },
            ],
        });
        expect(wrapper.find(".details").text()).toContain("Elements (major)");
    });

    it("lists the evidence analyses by name and opens one", async () => {
        const { wrapper, store } = mountCard([uuid(101)]);
        await flushPromises();
        const item = wrapper.find(".evidence button");
        expect(item.text()).toContain("Analysis 101");
        await item.trigger("click");
        expect(store.focus).toEqual({ kind: "analysis", id: uuid(101) });
    });

    it("adds the material and every evidence analysis in one step, those without data too", async () => {
        const { wrapper, store, summary } = mountCard([uuid(101), uuid(102)]);
        await flushPromises();
        await wrapper.find(".with-evidence button").trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual([
            `ch:${summary.id}:-`,
            `an:${uuid(101)}:-`,
            `an:${uuid(102)}:-`,
        ]);
        expect(wrapper.text()).not.toContain("no data to show");
    });

    it("refuses the batch when it does not fit", async () => {
        const { wrapper, store } = mountCard([uuid(101)]);
        store.addManyToBasket(
            Array.from({ length: 29 }, (_, n) => `an:${uuid(300 + n)}:-`),
        );
        await flushPromises();
        expect(
            wrapper.find(".with-evidence button").attributes("disabled"),
        ).toBeDefined();
        expect(store.basket).toHaveLength(29);
    });

    it("names its evidence without reading the analyses", async () => {
        const { wrapper, fetchMock } = mountCard([uuid(101), uuid(102)]);
        await flushPromises();
        expect(
            wrapper.findAll(".evidence button").map((item) => item.text()),
        ).toEqual(["Analysis 101", "Analysis 102"]);
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it("links a web source and writes an unsafe one as plain text", () => {
        const { wrapper } = mountCard([], {
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
        const { wrapper } = mountCard([]);
        await wrapper.find(".card-head .close").trigger("click");
        expect(wrapper.emitted("close")).toHaveLength(1);
    });

    it("offers the evidence of the material it shows, not the previous one's", async () => {
        const { wrapper, store } = mountCard([uuid(101)]);
        await wrapper.setProps({
            summary: characterization(2, {
                evidence: evidenceOf([uuid(102)]),
            }),
        });
        expect(wrapper.find(".evidence").text()).not.toContain("Analysis 101");
        expect(wrapper.find(".evidence").text()).toContain("Analysis 102");
        await wrapper.find(".with-evidence button").trigger("click");
        expect(store.basket.map((item) => item.key)).toContain(
            `an:${uuid(102)}:-`,
        );
        expect(store.basket.map((item) => item.key)).not.toContain(
            `an:${uuid(101)}:-`,
        );
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
