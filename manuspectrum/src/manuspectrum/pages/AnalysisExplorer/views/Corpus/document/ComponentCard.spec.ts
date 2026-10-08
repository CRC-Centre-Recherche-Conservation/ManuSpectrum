import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it } from "vitest";
import { defineComponent, h, nextTick } from "vue";

import ComponentCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/ComponentCard.vue";

import {
    analysisKey,
    characterizationKey,
} from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { useSelectionToggle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionToggle.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    documentComponent,
    label,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { DocumentComponent } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    ComponentAnalysis,
    ComponentMaterial,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/component-analyses.ts";

function entry(
    n: number,
    overrides: Partial<ComponentAnalysis> = {},
): ComponentAnalysis {
    return {
        id: uuid(100 + n),
        name: label(`X0${n}`),
        style: { key: "xrf", label: label("XRF"), code: "XRF", colour: 1 },
        unpublished: false,
        match: true,
        dataKind: "xy",
        ...overrides,
    };
}

function material(
    n: number,
    overrides: Partial<ComponentMaterial> = {},
): ComponentMaterial {
    return {
        id: uuid(500 + n),
        name: label(`Vermilion ${n}`),
        swatch: "#c00",
        certainty: label("Reliable"),
        unpublished: false,
        match: true,
        ...overrides,
    };
}

function mountCard(
    component: DocumentComponent = documentComponent(1),
    analyses: ComponentAnalysis[] = [entry(1), entry(2), entry(3)],
    materials: ComponentMaterial[] = [],
) {
    const pinia = createPinia();
    setActivePinia(pinia);
    mount(
        defineComponent({
            setup() {
                useSelectionToggle().dismiss();
                return () => h("div");
            },
        }),
        { global: { plugins: [pinia] } },
    );
    const wrapper = mount(ComponentCard, {
        props: { component, analyses, materials },
        global: { plugins: [pinia] },
    });
    return { wrapper, store: useExplorerStore() };
}

describe("ComponentCard", () => {
    it("names the component and counts its zones and the pages they sit on", () => {
        const zone = documentComponent(1).zones[0];
        const { wrapper } = mountCard(
            documentComponent(1, {
                zones: [
                    zone,
                    { ...zone, feature: uuid(960) },
                    { ...zone, feature: uuid(961), canvas: 1 },
                ],
            }),
        );
        expect(wrapper.find("h3").text()).toBe("Component 1");
        expect(wrapper.find(".meta").text()).toContain("3 zones on 2 pages");
    });

    it("says so when the component is only observed, without a zone", () => {
        const { wrapper } = mountCard(documentComponent(1, { zones: [] }));
        expect(wrapper.find(".meta").text()).toContain("No zone");
    });

    it("marks a draft component", () => {
        const { wrapper } = mountCard(
            documentComponent(1, { unpublished: true }),
        );
        expect(wrapper.find(".badge.draft").text()).toBe("Draft");
        expect(mountCard().wrapper.find(".badge.draft").exists()).toBe(false);
    });

    it("lists its analyses with a Selection checkbox each, the technique code and a name button", () => {
        const { wrapper } = mountCard();
        const rows = wrapper.findAll(".analyses li");
        expect(rows).toHaveLength(3);
        expect(
            rows.map((row) => row.find("button[data-focus]").text()),
        ).toEqual(["X01", "X02", "X03"]);
        expect(rows[0].find(".technique-code").text()).toBe("XRF");
        expect(
            rows[0].find("input[type=checkbox]").attributes("aria-label"),
        ).toBe("Add X01 to the Selection");
    });

    it("ticks one analysis in the Selection by its an: key", async () => {
        const { wrapper, store } = mountCard();
        await wrapper
            .findAll(".analyses li input[type=checkbox]")[1]
            .setValue(true);
        expect(store.basket.map((item) => item.key)).toEqual([
            analysisKey(uuid(102)),
        ]);
    });

    it("ticks every analysis from the select-all box", async () => {
        const { wrapper, store } = mountCard();
        await wrapper
            .find(".analyses .select-all-checkbox input")
            .setValue(true);
        expect(store.basket.map((item) => item.key)).toEqual([
            analysisKey(uuid(101)),
            analysisKey(uuid(102)),
            analysisKey(uuid(103)),
        ]);
    });

    it("names the select-all by its scope and shows the counter chip", () => {
        const { wrapper } = mountCard();
        const box = wrapper.get(".analyses .select-all-checkbox");
        expect(box.get("input").attributes("aria-label")).toBe(
            "Select all: the 3 analyses on this page",
        );
        expect(box.get(".text").text()).toBe("Select all");
        expect(box.get(".chip").text()).toBe("3");
    });

    it("puts the notice above the select-all when the analyses do not fit", () => {
        const { store, wrapper } = mountCard();
        store.addManyToBasket(
            Array.from({ length: 28 }, (_, n) => analysisKey(uuid(900 + n))),
        );
        return nextTick().then(() => {
            const children = [...wrapper.get(".analyses").element.children].map(
                (node) => node.className.split(" ")[0],
            );
            expect(children.slice(1, 3)).toEqual([
                "selection-capacity-notice",
                "select-all-checkbox",
            ]);
            expect(
                wrapper
                    .get(".analyses .select-all-checkbox input")
                    .attributes("aria-describedby"),
            ).toBe(wrapper.get(".selection-capacity-notice").attributes("id"));
        });
    });

    it("shows its own status line under the select-all after a bulk add", async () => {
        const { wrapper } = mountCard();
        await wrapper
            .get(".analyses .select-all-checkbox input")
            .setValue(true);
        const children = [...wrapper.get(".analyses").element.children].map(
            (node) => node.className.split(" ")[0],
        );
        expect(children.slice(1, 3)).toEqual([
            "select-all-checkbox",
            "bulk-status-line",
        ]);
        expect(wrapper.get(".analyses .bulk-status-line").text()).toContain(
            "3 analyses added (A1 to A3).",
        );
    });

    it("adds all its analyses at once, an: keys only, with the hints naming the component", async () => {
        const { wrapper, store } = mountCard();
        const add = wrapper.get(".selection-actions button.primary");
        expect(add.text()).toBe("With its 3 analyses");
        await add.trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual([
            analysisKey(uuid(101)),
            analysisKey(uuid(102)),
            analysisKey(uuid(103)),
        ]);
        expect(store.basket.every((item) => item.key.startsWith("an:"))).toBe(
            true,
        );
    });

    it("adds all or nothing when the Selection cannot hold them", async () => {
        const { wrapper, store } = mountCard();
        for (let n = 0; n < 29; n += 1) {
            store.addToBasket(analysisKey(uuid(900 + n)));
        }
        await nextTick();
        const add = wrapper.get(".selection-actions button.primary");
        expect(add.attributes("disabled")).toBeDefined();
        expect(store.basket).toHaveLength(29);
        expect(wrapper.find(".selection-actions .reason").text()).toContain(
            "3 items",
        );
    });

    it("offers no group add without an analysis", () => {
        const { wrapper } = mountCard(documentComponent(1), []);
        expect(wrapper.find(".selection-actions button.primary").exists()).toBe(
            false,
        );
        expect(wrapper.text()).toContain("No analysis of this document");
    });

    it("greys an analysis the filters drop and badges it once in its name", () => {
        const { wrapper } = mountCard(documentComponent(1), [
            entry(1, { match: false }),
        ]);
        const row = wrapper.get(".analyses li");
        expect(row.classes()).toContain("is-dimmed");
        expect(row.get("button .outside").text()).toBe("outside filters");
        expect(
            row
                .get("button")
                .text()
                .match(/outside/g),
        ).toHaveLength(1);
        expect(row.find(".visually-hidden").exists()).toBe(false);
    });

    it("opens an analysis on the analyses view from its name", async () => {
        const { wrapper, store } = mountCard();
        store.openDocument(uuid(1));
        await wrapper
            .findAll(".analyses button[data-focus]")[2]
            .trigger("click");
        expect(store.focus).toEqual({ kind: "analysis", id: uuid(103) });
    });

    it("closes through an icon button named « Close the card », described by Escape", async () => {
        const { wrapper } = mountCard();
        const button = wrapper.find("button.close");
        const named = (attribute: string) =>
            wrapper.find(`[id="${button.attributes(attribute)}"]`).text();
        expect(named("aria-labelledby")).toBe("Close the card");
        expect(named("aria-describedby")).toBe("Escape");
        await button.trigger("click");
        expect(wrapper.emitted("close")).toHaveLength(1);
    });

    it("hides the close button where the container has its own, and gives the heading the id it is labelled by", () => {
        const pinia = createPinia();
        setActivePinia(pinia);
        const wrapper = mount(ComponentCard, {
            props: {
                component: documentComponent(1),
                analyses: [],
                closable: false,
                headingId: "card-heading",
            },
            global: { plugins: [pinia] },
        });
        expect(wrapper.find("button.close").exists()).toBe(false);
        expect(wrapper.find("h3").attributes("id")).toBe("card-heading");
    });

    describe("identified materials", () => {
        const withMaterials = () =>
            mountCard(
                documentComponent(1),
                [entry(1), entry(2)],
                [
                    material(1),
                    material(2, {
                        swatch: null,
                        certainty: null,
                        match: false,
                    }),
                ],
            );

        it("lists them under the analyses with the swatch, the certainty and a Selection checkbox", () => {
            const { wrapper } = withMaterials();
            expect(wrapper.find(".materials h4").text()).toBe(
                "Identified materials (2)",
            );
            const rows = wrapper.findAll(".materials li");
            expect(rows).toHaveLength(2);
            expect(rows[0].find("[data-focus]").text()).toBe("Vermilion 1");
            expect(rows[0].find(".swatch").attributes("style")).toContain(
                "background",
            );
            expect(rows[0].find(".certainty").text()).toBe("Reliable");
            expect(
                rows[0].find("input[type=checkbox]").attributes("aria-label"),
            ).toBe("Add Vermilion 1 to the Selection");
            expect(rows[1].find(".swatch").exists()).toBe(false);
            expect(rows[1].find(".certainty").exists()).toBe(false);
            expect(rows[1].classes()).toContain("is-dimmed");
        });

        it("has no materials section without a material", () => {
            expect(mountCard().wrapper.find(".materials").exists()).toBe(false);
        });

        it("ticks one material by its ch: key", async () => {
            const { wrapper, store } = withMaterials();
            await wrapper
                .findAll(".materials li input[type=checkbox]")[0]
                .setValue(true);
            expect(store.basket.map((item) => item.key)).toEqual([
                characterizationKey(uuid(501)),
            ]);
        });

        it("opens the Characterization card from the name", async () => {
            const { wrapper, store } = withMaterials();
            store.openDocument(uuid(1));
            await wrapper
                .findAll(".materials [data-focus]")[1]
                .trigger("click");
            expect(store.focus).toEqual({
                kind: "characterization",
                id: uuid(502),
            });
        });

        it("offers the analyses and materials together, or the analyses alone", async () => {
            const { wrapper, store } = withMaterials();
            const buttons = wrapper.findAll(".selection-actions button");
            expect(buttons[0].text()).toBe(
                "With its 2 analyses and 2 materials",
            );
            expect(buttons[1].text()).toBe("The analyses alone");
            await buttons[0].trigger("click");
            expect(store.basket.map((item) => item.key)).toEqual([
                analysisKey(uuid(101)),
                analysisKey(uuid(102)),
                characterizationKey(uuid(501)),
                characterizationKey(uuid(502)),
            ]);
        });

        it("adds the analyses alone without the materials", async () => {
            const { wrapper, store } = withMaterials();
            await wrapper
                .findAll(".selection-actions button")[1]
                .trigger("click");
            expect(store.basket.map((item) => item.key)).toEqual([
                analysisKey(uuid(101)),
                analysisKey(uuid(102)),
            ]);
        });

        it("refuses the whole group when it does not fit, and says why, while the analyses alone still fit", async () => {
            const { wrapper, store } = withMaterials();
            for (let n = 0; n < 27; n += 1) {
                store.addToBasket(analysisKey(uuid(900 + n)));
            }
            await nextTick();
            const buttons = wrapper.findAll(".selection-actions button");
            expect(buttons[0].attributes("disabled")).toBeDefined();
            expect(buttons[1].attributes("disabled")).toBeUndefined();
            expect(wrapper.find(".selection-actions .reason").text()).toContain(
                "4 items",
            );
        });

        it("offers its materials alone when no analysis observes the component", async () => {
            const { wrapper, store } = mountCard(
                documentComponent(1),
                [],
                [material(1), material(2)],
            );
            const buttons = wrapper.findAll(".selection-actions button");
            expect(buttons).toHaveLength(1);
            expect(buttons[0].text()).toBe("With its 2 materials");
            await buttons[0].trigger("click");
            expect(store.basket).toHaveLength(2);
        });
    });
});
