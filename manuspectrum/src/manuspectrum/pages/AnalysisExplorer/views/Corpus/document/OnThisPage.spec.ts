import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { defineComponent, h } from "vue";

import OnThisPage from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/OnThisPage.vue";

import { useSelectionToggle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionToggle.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { analysisKey } from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { techniqueStyles } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import {
    annotation,
    characterization,
    documentComponent,
    label,
    sample,
    technique,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

let pinia = createPinia();

beforeEach(() => {
    pinia = createPinia();
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
});

function fillSelection(count: number): void {
    useExplorerStore().addManyToBasket(
        Array.from({ length: count }, (_, n) => analysisKey(uuid(900 + n))),
    );
}

function unlocatedEntry(n: number, match = true) {
    return {
        analysis: uuid(150 + n),
        name: label(`FORS_0${n}`),
        technique: null,
        dataKind: "xy",
        unpublished: false,
        component: null,
        match,
    };
}

function mountList(props: Record<string, unknown>) {
    const annotations =
        (props.annotations as ReturnType<typeof annotation>[]) ?? [];
    return mount(OnThisPage, {
        global: { plugins: [pinia] },
        props: {
            annotations,
            unlocated: [],
            characterizations: [],
            samples: [],
            view: "analyses",
            styles: techniqueStyles(
                annotations.map((a) => a.technique),
                label("Analysis"),
            ),
            ...props,
        },
    });
}

describe("OnThisPage", () => {
    it("lists the components of the page in the analyses view and opens one", async () => {
        const wrapper = mountList({
            annotations: [annotation(1)],
            components: [
                documentComponent(1),
                documentComponent(2, { unpublished: true, zones: [] }),
            ],
        });
        const block = wrapper.get(".components");
        expect(block.get("h4").text()).toBe("Components on this page");
        expect(
            block
                .findAll("button")
                .map((button) => button.attributes("data-focus")),
        ).toEqual([`component:${uuid(701)}`, `component:${uuid(702)}`]);
        expect(block.text()).toContain("Component 2");
        expect(block.findAll(".draft")).toHaveLength(1);
        expect(block.find("input").exists()).toBe(false);
        await block.findAll("button")[1].trigger("click");
        expect(wrapper.emitted("select")?.at(-1)).toEqual([
            { kind: "component", id: uuid(702) },
        ]);
    });

    it("lists no component block without a component or outside the analyses view", () => {
        expect(
            mountList({ annotations: [annotation(1)] })
                .find(".components")
                .exists(),
        ).toBe(false);
        expect(
            mountList({
                annotations: [annotation(1)],
                components: [documentComponent(1)],
                samples: [sample(1)],
                view: "samples",
            })
                .find(".components")
                .exists(),
        ).toBe(false);
    });

    it("groups the analyses of the page by technique", () => {
        const annotations = [
            annotation(1),
            annotation(2, { technique: technique("t:fors", "FORS", 2) }),
            annotation(3),
        ];
        const wrapper = mountList({ annotations });
        const groups = wrapper.findAll(".technique");
        expect(groups.map((g) => g.find("h4").text())).toEqual([
            expect.stringContaining("FORS"),
            expect.stringContaining("XRF"),
        ]);
        expect(groups[1].findAll("li")).toHaveLength(2);
    });

    it("opens an analysis from the list", async () => {
        const wrapper = mountList({ annotations: [annotation(1)] });
        await wrapper.find(".technique button").trigger("click");
        expect(wrapper.emitted("select")?.[0]).toEqual([
            { kind: "analysis", id: uuid(101) },
        ]);
    });

    it("greys an analysis outside the filters and ends its row with a visible badge", () => {
        const wrapper = mountList({
            annotations: [annotation(1, { match: false })],
        });
        const row = wrapper.find(".technique li");
        expect(row.classes()).toContain("is-dimmed");
        const badge = row.find("button .outside");
        expect(badge.text()).toBe("outside filters");
        expect(badge.classes()).not.toContain("visually-hidden");
        expect(row.find(".visually-hidden").exists()).toBe(false);
    });

    it("names an analysis outside the filters once, by its badge", () => {
        const wrapper = mountList({
            annotations: [annotation(1, { match: false })],
        });
        const text = wrapper.get(".technique li button").text();
        expect(text.match(/outside/g)).toHaveLength(1);
    });

    it("puts the badge on an unlocated analysis outside the filters", () => {
        const wrapper = mountList({
            annotations: [],
            unlocated: [unlocatedEntry(1, false), unlocatedEntry(2)],
        });
        const rows = wrapper.findAll(".unlocated li");
        expect(rows[0].find(".outside").text()).toBe("outside filters");
        expect(rows[1].find(".outside").exists()).toBe(false);
    });

    it("lists the groups with no analysis kept after the others, in their order otherwise", () => {
        const codes = ["XRF", "FORS", "Raman"];
        const make = (outside: string) => [
            annotation(1, { match: outside !== "XRF" }),
            annotation(2, {
                technique: technique("t:fors", "FORS", 2),
                match: outside !== "FORS",
            }),
            annotation(3, {
                technique: technique("t:raman", "Raman", 3),
                match: outside !== "Raman",
            }),
        ];
        const titles = (outside: string) =>
            mountList({ annotations: make(outside) })
                .findAll(".technique .group-title")
                .map((title) => title.text());
        const base = titles("none");
        expect(base).toHaveLength(3);
        for (const code of codes) {
            const dimmed = base.find((title) => title.includes(code))!;
            expect(titles(code)).toEqual([
                ...base.filter((title) => title !== dimmed),
                dimmed,
            ]);
        }
    });

    it("keeps the groups in their order when no analysis is outside the filters", () => {
        const annotations = [
            annotation(1),
            annotation(2, { technique: technique("t:fors", "FORS", 2) }),
        ];
        const titles = mountList({ annotations })
            .findAll(".technique .group-title")
            .map((title) => title.text());
        const reversed = mountList({ annotations: [...annotations].reverse() })
            .findAll(".technique .group-title")
            .map((title) => title.text());
        expect(titles).toEqual(reversed);
    });

    it("gives a row inside the filters no extra accessible text", () => {
        const wrapper = mountList({ annotations: [annotation(1)] });
        expect(wrapper.find(".technique li .visually-hidden").exists()).toBe(
            false,
        );
    });

    it("puts a Selection checkbox on each analysis row", async () => {
        const wrapper = mountList({ annotations: [annotation(1)] });
        const box = wrapper.find(".technique li input[type=checkbox]");
        expect(box.attributes("aria-label")).toContain("Add");
        await box.setValue(true);
        expect(useExplorerStore().basket.map((item) => item.key)).toEqual([
            analysisKey(uuid(101)),
        ]);
    });

    it("has a select-all per technique group that covers only the analyses listed", async () => {
        const store = useExplorerStore();
        const wrapper = mountList({
            annotations: [
                annotation(1),
                annotation(2),
                annotation(3, { technique: technique("t:fors", "FORS", 2) }),
            ],
        });
        const groups = wrapper.findAll(".technique");
        const master = groups[1].find(".select-all-checkbox input");
        expect(
            groups[1]
                .find(".select-all-checkbox input")
                .attributes("aria-label"),
        ).toBe("Select all: XRF (2)");
        await master.setValue(true);
        expect(store.basket.map((item) => item.key).sort()).toEqual(
            [analysisKey(uuid(101)), analysisKey(uuid(102))].sort(),
        );
    });

    it("has a select-all for the whole page over the analyses with and without a position", async () => {
        const store = useExplorerStore();
        const wrapper = mountList({
            annotations: [annotation(1)],
            unlocated: [unlocatedEntry(1)],
        });
        await wrapper.find(".unlocated .fold").trigger("click");
        const page = wrapper.find(".page-select .select-all-checkbox");
        expect(page.text()).toBe("Select all2");
        expect(page.find("input").attributes("aria-label")).toBe(
            "Select all: the 2 analyses on this page",
        );
        await page.find("input").setValue(true);
        expect(store.basket).toHaveLength(2);
    });

    it("has a select-all for the analyses without a position when they are listed", async () => {
        const store = useExplorerStore();
        const wrapper = mountList({
            unlocated: [unlocatedEntry(1), unlocatedEntry(2)],
        });
        const master = wrapper.find(".unlocated .select-all-checkbox");
        expect(master.find("input").attributes("aria-label")).toBe(
            "Select all: Without a position on the image (2)",
        );
        await master.find("input").setValue(true);
        expect(store.basket.map((item) => item.key).sort()).toEqual(
            [analysisKey(uuid(151)), analysisKey(uuid(152))].sort(),
        );
    });

    it("counts only the displayed rows: no master for folded analyses without a position", () => {
        const wrapper = mountList({
            annotations: [annotation(1)],
            unlocated: [unlocatedEntry(1)],
        });
        expect(wrapper.find(".unlocated .select-all-checkbox").exists()).toBe(
            false,
        );
        expect(
            wrapper.find(".page-select input").attributes("aria-label"),
        ).toBe("Select all: the 1 analysis on this page");
    });

    describe("capacity", () => {
        it("puts the notice before the select-all", () => {
            fillSelection(28);
            const wrapper = mountList({
                annotations: [annotation(1), annotation(2), annotation(3)],
            });
            const children = [
                ...wrapper.get(".page-select").element.children,
            ].map((node) => node.className.split(" ")[0]);
            expect(children).toEqual([
                "selection-capacity-notice",
                "select-all-checkbox",
            ]);
        });

        it("describes the page and group checkboxes by the notice while it is shown", () => {
            fillSelection(28);
            const wrapper = mountList({
                annotations: [annotation(1), annotation(2), annotation(3)],
            });
            const notice = wrapper.get(".selection-capacity-notice");
            expect(notice.get(".title").text()).toBe(
                "Only 2 places left in the Selection",
            );
            expect(
                wrapper
                    .get(".page-select .select-all-checkbox input")
                    .attributes("aria-describedby"),
            ).toBe(notice.attributes("id"));
            expect(
                wrapper
                    .get(".technique .select-all-checkbox input")
                    .attributes("aria-describedby"),
            ).toBe(notice.attributes("id"));
        });

        it("shows the status line right under the select-all after a bulk add", async () => {
            const wrapper = mountList({
                annotations: [annotation(1), annotation(2)],
            });
            await wrapper.get(".page-select input").setValue(true);
            const children = [
                ...wrapper.get(".page-select").element.children,
            ].map((node) => node.className.split(" ")[0]);
            expect(children).toEqual([
                "select-all-checkbox",
                "bulk-status-line",
            ]);
            expect(wrapper.get(".bulk-status-line .message").text()).toBe(
                "2 analyses added (A1 to A2).",
            );
        });

        it("shows no notice once the whole page is held", async () => {
            const wrapper = mountList({ annotations: [annotation(1)] });
            fillSelection(29);
            useExplorerStore().addToBasket(analysisKey(uuid(101)));
            await wrapper.vm.$nextTick();
            expect(wrapper.find(".selection-capacity-notice").exists()).toBe(
                false,
            );
        });
    });

    it("says how many analyses outside the filters are hidden", () => {
        const none = mountList({ annotations: [annotation(1)] });
        expect(none.find(".hidden-note").exists()).toBe(false);
        const some = mountList({
            annotations: [annotation(1)],
            hiddenCount: 3,
        });
        expect(some.find(".hidden-note").text()).toBe(
            "3 analyses outside the filters are hidden.",
        );
        const one = mountList({ annotations: [annotation(1)], hiddenCount: 1 });
        expect(one.find(".hidden-note").text()).toBe(
            "1 analysis outside the filters is hidden.",
        );
    });

    it("leaves out the page and document a row name repeats", () => {
        const wrapper = mountList({
            annotations: [
                annotation(1, {
                    name: label("Zone bleue — 70r — Grenoble, Ms.76 Rés."),
                }),
            ],
            pageLabel: "70r",
            documentName: "Grenoble. Bibliothèque municipale, Ms.76 Rés.",
        });
        expect(wrapper.find(".technique li button").text()).toBe("Zone bleue");
        const bare = mountList({
            annotations: [annotation(2, { name: label("XRF — 70v — spot 2") })],
            pageLabel: "70r",
        });
        expect(bare.find(".technique li button").text()).toBe(
            "XRF — 70v — spot 2",
        );
    });

    it("folds the unlocated analyses under a count when the page has its own", async () => {
        const unlocated = [
            {
                analysis: uuid(150),
                name: label("FORS_014"),
                technique: null,
                dataKind: "xy",
                unpublished: false,
                match: true,
            },
        ];
        const wrapper = mountList({ annotations: [annotation(1)], unlocated });
        const toggle = wrapper.find(".unlocated .fold");
        expect(toggle.text()).toBe("Without a position on the image (1)");
        expect(toggle.attributes("aria-expanded")).toBe("false");
        expect(wrapper.find(".unlocated").text()).not.toContain("FORS_014");
        await toggle.trigger("click");
        expect(wrapper.find(".unlocated").text()).toContain("FORS_014");
    });

    it("lists the unlocated analyses under their own heading", () => {
        const unlocated = [
            {
                analysis: uuid(150),
                name: label("FORS_014"),
                technique: null,
                dataKind: "xy",
                unpublished: false,
                match: true,
            },
        ];
        const wrapper = mountList({ unlocated });
        expect(wrapper.find(".unlocated").text()).toContain(
            "Without a position on the image",
        );
        expect(wrapper.find(".unlocated").text()).toContain("FORS_014");
    });

    it("lists only the identified materials of the page in the materials view", async () => {
        const summary = characterization(1);
        const wrapper = mountList({
            annotations: [annotation(1)],
            characterizations: [summary],
            samples: [sample(1)],
            view: "characterizations",
        });
        expect(wrapper.find(".technique").exists()).toBe(false);
        expect(wrapper.find(".samples").exists()).toBe(false);
        await wrapper.find(".materials button").trigger("click");
        expect(wrapper.emitted("select")?.[0]).toEqual([
            { kind: "characterization", id: summary.id },
        ]);
    });

    it("lists only the analyses in the analyses view", () => {
        const wrapper = mountList({
            annotations: [annotation(1)],
            characterizations: [characterization(1)],
            samples: [sample(1)],
        });
        expect(wrapper.find(".technique").exists()).toBe(true);
        expect(wrapper.find(".materials").exists()).toBe(false);
        expect(wrapper.find(".samples").exists()).toBe(false);
    });

    it("lists only the samples in the samples view and opens one", async () => {
        const wrapper = mountList({
            annotations: [annotation(1)],
            characterizations: [characterization(1)],
            samples: [sample(1, { unpublished: true })],
            view: "samples",
        });
        expect(wrapper.find(".technique").exists()).toBe(false);
        expect(wrapper.find(".materials").exists()).toBe(false);
        expect(wrapper.find(".samples").text()).toContain("Sample 1");
        expect(wrapper.find(".samples").text()).toContain("Draft");
        await wrapper.find(".samples button").trigger("click");
        expect(wrapper.emitted("select")?.[0]).toEqual([
            { kind: "sample", id: uuid(601) },
        ]);
    });

    it("says when the page has no sample in the samples view", () => {
        expect(mountList({ view: "samples" }).text()).toContain(
            "No sample on this page.",
        );
    });

    it("says when the page has no analysis", () => {
        expect(mountList({}).text()).toContain(
            "No published analysis on this page.",
        );
    });
});
