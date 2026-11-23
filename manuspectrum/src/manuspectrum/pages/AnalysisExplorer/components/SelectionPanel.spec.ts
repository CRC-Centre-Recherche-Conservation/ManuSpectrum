import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { computed, nextTick, ref } from "vue";

import SelectionPanel from "@/manuspectrum/pages/AnalysisExplorer/components/SelectionPanel.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    SELECTION_HINTS_KEY,
    SELECTION_ITEMS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    documentHref,
    snapshotOf,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";
import {
    analysisHit,
    characterization,
    fileEntry,
    imagingEntry,
    label,
    technique,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Item } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestStatus } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import type { SelectionItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionItems.ts";

vi.mock("@/arches_vue_components/application/generate-arches-url.ts", () => ({
    generateArchesURL: () => "/en/api/explorer/items",
}));

enableAutoUnmount(afterEach);
afterEach(() => vi.unstubAllGlobals());

const KEY = `af:${uuid(101)}:${uuid(700)}`;
const GONE = `af:${uuid(102)}:${uuid(701)}`;

function mountPanel() {
    vi.stubGlobal(
        "fetch",
        vi.fn(async () =>
            jsonResponse({
                items: [
                    {
                        key: KEY,
                        kind: "analysis-file",
                        analysis: analysisHit(1),
                        file: fileEntry(),
                    },
                ],
                missing: [GONE],
            }),
        ),
    );
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useExplorerStore();
    store.addManyToBasket([KEY, GONE]);
    return {
        wrapper: mount(SelectionPanel, {
            attachTo: document.body,
            global: { plugins: [pinia] },
        }),
        store,
    };
}

beforeEach(() => forgetPayloads());

describe("SelectionPanel", () => {
    it("holds a placeholder line in each row until its item is read", () => {
        const { wrapper } = mountPanel();
        const row = wrapper.find(`[data-key="${KEY}"]`);
        expect(row.find(".pending").exists()).toBe(true);
        expect(row.find(".pending").attributes("aria-label")).toBe("Loading…");
    });

    it("lays out a column whose list is the only scroller and whose footer comes after it", () => {
        const { wrapper } = mountPanel();
        const children = [...wrapper.element.children].map(
            (child) => child.tagName + "." + child.className,
        );
        expect(children.at(0)).toMatch(/^HEADER/);
        expect(children.at(-1)).toMatch(/^FOOTER\.foot/);
        expect(children.at(-2)).toMatch(/^OL/);
        const foot = wrapper.get("footer.foot");
        expect(foot.find(".actions .compare").exists()).toBe(true);
        expect(wrapper.get("ol").element.contains(foot.element)).toBe(false);
    });

    it("keeps the undo line in the footer after the Selection is emptied", async () => {
        const { wrapper } = mountPanel();
        await wrapper.get(".clear").trigger("click");
        await nextTick();
        const foot = wrapper.get("footer.foot");
        expect(foot.find('[data-action="undo"]').exists()).toBe(true);
        expect(foot.find(".actions").exists()).toBe(false);
    });

    it("says the Selection is kept on this browser", () => {
        const { wrapper } = mountPanel();
        expect(wrapper.find(".kept").text()).toBe("Kept on this browser");
    });

    it("shows what the card knew of an item while it loads, and asks only for new keys", async () => {
        const fetchMock = vi.fn(async (url: string) =>
            jsonResponse({
                items: new URLSearchParams(url.split("?")[1])
                    .getAll("ids")
                    .map((key) => ({
                        key,
                        kind: "analysis-file",
                        analysis: analysisHit(1),
                        file: fileEntry(),
                    })),
                missing: [],
            }),
        );
        vi.stubGlobal("fetch", fetchMock);
        const pinia = createPinia();
        setActivePinia(pinia);
        const store = useExplorerStore();
        const hints = ref(new Map());
        const wrapper = mount(SelectionPanel, {
            global: {
                plugins: [pinia],
                provide: { [SELECTION_HINTS_KEY as symbol]: hints },
            },
        });
        store.addToBasket(KEY);
        await flushPromises();
        hints.value = new Map([
            [GONE, { title: label("Zone bleue"), kind: "spectrum" }],
        ]);
        store.addToBasket(GONE);
        await nextTick();
        expect(wrapper.find(`[data-key="${GONE}"]`).text()).toContain(
            "Zone bleue",
        );
        await flushPromises();
        const asked = fetchMock.mock.calls.map(([url]) =>
            new URLSearchParams(String(url).split("?")[1]).getAll("ids"),
        );
        expect(asked).toEqual([[KEY], [GONE]]);
    });

    it("shows the items the shell's reading of the Selection holds, with no request of its own", async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal("fetch", fetchMock);
        const pinia = createPinia();
        setActivePinia(pinia);
        useExplorerStore().addManyToBasket([KEY]);
        const shared: SelectionItems = {
            byKey: ref(
                new Map<string, Item>([
                    [
                        KEY,
                        {
                            key: KEY,
                            kind: "analysis-file",
                            excitation: null,
                            analysis: analysisHit(1),
                            file: fileEntry(),
                        },
                    ],
                ]),
            ),
            missing: ref(new Set<string>()),
            settled: computed(() => true),
            status: ref<RequestStatus>("ready"),
            retry: () => undefined,
        };
        const wrapper = mount(SelectionPanel, {
            global: {
                plugins: [pinia],
                provide: { [SELECTION_ITEMS_KEY as symbol]: () => shared },
            },
        });
        await flushPromises();
        expect(wrapper.find(`[data-key="${KEY}"]`).text()).toContain(
            "Manuscript 1",
        );
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it("offers Retry instead of placeholders when the Selection cannot be read", async () => {
        const pinia = createPinia();
        setActivePinia(pinia);
        useExplorerStore().addManyToBasket([KEY]);
        const retry = vi.fn();
        const shared: SelectionItems = {
            byKey: ref(new Map<string, Item>()),
            missing: ref(new Set<string>()),
            settled: computed(() => false),
            status: ref<RequestStatus>("error"),
            retry,
        };
        const wrapper = mount(SelectionPanel, {
            global: {
                plugins: [pinia],
                provide: { [SELECTION_ITEMS_KEY as symbol]: () => shared },
            },
        });

        expect(wrapper.find(".pending").exists()).toBe(false);
        expect(wrapper.find(".unavailable-state").text()).toContain(
            "The service is not answering right now.",
        );
        await wrapper.find(".unavailable-state .retry").trigger("click");
        expect(retry).toHaveBeenCalledTimes(1);
    });

    it("lists the Selection with its A-labels and kinds", async () => {
        const { wrapper } = mountPanel();
        await flushPromises();
        const first = wrapper.find(`[data-key="${KEY}"]`);
        expect(first.text()).toContain("A1");
        expect(first.text()).toContain("spectrum");
        expect(first.text()).toContain("Manuscript 1");
    });

    it("shows a whole analysis with its technique and what it holds", async () => {
        const key = `an:${uuid(101)}:-`;
        vi.stubGlobal(
            "fetch",
            vi.fn(async () =>
                jsonResponse({
                    items: [
                        {
                            key,
                            kind: "analysis",
                            analysis: analysisHit(1, {
                                technique: technique(
                                    "http://example.org/xrf",
                                    "X-ray fluorescence",
                                    4,
                                    uuid(900),
                                    "XRF",
                                ),
                            }),
                            files: [
                                fileEntry({ id: uuid(700) }),
                                fileEntry({ id: uuid(701) }),
                                imagingEntry(),
                            ],
                        },
                    ],
                    missing: [],
                }),
            ),
        );
        const pinia = createPinia();
        setActivePinia(pinia);
        useExplorerStore().addManyToBasket([key]);
        const wrapper = mount(SelectionPanel, { global: { plugins: [pinia] } });
        await flushPromises();
        const row = wrapper.find(`[data-key="${key}"]`);
        expect(row.find(".title").text()).toBe("MS1_f12_XRF_03");
        expect(row.find(".technique-tag .code").text()).toBe("XRF");
        expect(row.find(".technique-tag .dot").classes("dot--tech-4")).toBe(
            true,
        );
        expect(row.find(".kind").text()).toBe("2 spectra · 1 map");
        expect(row.text()).toContain("Manuscript 1");
    });

    it("says an analysis in the Selection holds no data to show", async () => {
        const key = `an:${uuid(101)}:-`;
        vi.stubGlobal(
            "fetch",
            vi.fn(async () =>
                jsonResponse({
                    items: [
                        {
                            key,
                            kind: "analysis",
                            analysis: analysisHit(1),
                            files: [],
                        },
                    ],
                    missing: [],
                }),
            ),
        );
        const pinia = createPinia();
        setActivePinia(pinia);
        useExplorerStore().addManyToBasket([key]);
        const wrapper = mount(SelectionPanel, { global: { plugins: [pinia] } });
        await flushPromises();
        expect(wrapper.find(`[data-key="${key}"] .kind`).text()).toBe(
            "no data to show",
        );
    });

    it("marks an item that is no longer available and lets the reader remove it", async () => {
        const { wrapper, store } = mountPanel();
        await flushPromises();
        const gone = wrapper.find(`[data-key="${GONE}"]`);
        expect(gone.text()).toContain("no longer available");
        await gone.find("button.remove").trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual([KEY]);
    });

    it("puts Compare (n) first as the primary action and Empty… second", async () => {
        const { wrapper } = mountPanel();
        await flushPromises();
        const buttons = wrapper.findAll(".actions button");
        expect(buttons.map((button) => button.text())).toEqual([
            "Compare (2)",
            "Empty…",
        ]);
        expect(buttons[0].classes()).toContain("primary");
        expect(buttons[1].classes()).toContain("secondary");
        expect(buttons[1].classes()).not.toContain("primary");
    });

    it("empties the Selection without asking, then offers Undo", async () => {
        const { wrapper, store } = mountPanel();
        await flushPromises();
        await wrapper.find("button.clear").trigger("click");
        expect(store.basket).toEqual([]);
        const line = wrapper.get('[role="status"]');
        expect(line.text()).toContain("Selection emptied (2).");
        expect(wrapper.find(".actions").exists()).toBe(false);
    });

    it("restores the emptied Selection at the same slots with Undo", async () => {
        const { wrapper, store } = mountPanel();
        await flushPromises();
        const before = store.basket.map((item) => [item.key, item.slot]);
        await wrapper.find("button.clear").trigger("click");
        await wrapper.get('[data-action="undo"]').trigger("click");
        expect(store.basket.map((item) => [item.key, item.slot])).toEqual(
            before,
        );
        expect(wrapper.find('[role="status"]').exists()).toBe(false);
    });

    it("moves the focus to Undo when the buttons it was on are gone", async () => {
        const { wrapper } = mountPanel();
        await flushPromises();
        await wrapper.find("button.clear").trigger("click");
        await flushPromises();
        expect(document.activeElement).toBe(
            wrapper.get('[data-action="undo"]').element,
        );
    });

    it("opens the Compare view and says so, for a drawer holding it to close", async () => {
        const { wrapper, store } = mountPanel();
        await flushPromises();
        await wrapper.find("button.compare").trigger("click");
        expect(store.view).toBe("compare");
        expect(wrapper.emitted("compare")).toHaveLength(1);
    });

    it("writes a map layer's label apart from the analysis name and its language", async () => {
        const key = `im:${uuid(101)}:1`;
        vi.stubGlobal(
            "fetch",
            vi.fn(async () =>
                jsonResponse({
                    items: [
                        {
                            key,
                            kind: "imaging",
                            analysis: analysisHit(1, {
                                name: { value: "Analyse maXRF", lang: "fr" },
                            }),
                            file: imagingEntry(),
                        },
                    ],
                    missing: [],
                }),
            ),
        );
        const pinia = createPinia();
        setActivePinia(pinia);
        useExplorerStore().addManyToBasket([key]);
        const wrapper = mount(SelectionPanel, { global: { plugins: [pinia] } });
        await flushPromises();
        const title = wrapper.find(`[data-key="${key}"] .title`);
        expect(title.find('[lang="fr"]').text()).toBe("Analyse maXRF");
        expect(title.text()).toContain("Hg");
        expect(title.find('[lang="fr"]').text()).not.toContain("Hg");
    });
});

const CANVAS = "https://example.org/canvas/3";
const DOCUMENT = {
    id: uuid(1),
    model: "document",
    name: label("Manuscript 1"),
};

function itemsOf(...items: Item[]): SelectionItems {
    return {
        byKey: ref(new Map<string, Item>(items.map((i) => [i.key, i]))),
        missing: ref(new Set<string>()),
        settled: computed(() => true),
        status: ref<RequestStatus>("ready"),
        retry: () => undefined,
    };
}

function mountItems(...items: Item[]) {
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useExplorerStore();
    store.addManyToBasket(items.map((item) => item.key));
    const shared = itemsOf(...items);
    const wrapper = mount(SelectionPanel, {
        attachTo: document.body,
        global: {
            plugins: [pinia],
            provide: { [SELECTION_ITEMS_KEY as symbol]: () => shared },
        },
    });
    return { wrapper, store };
}

const HIT = analysisHit(1, { canvas: CANVAS });
const ANALYSIS_KEY = `an:${HIT.id}:-`;
const FILE_KEY = `af:${HIT.id}:${uuid(700)}`;
const IMAGING_KEY = `im:${HIT.id}:1`;
const MATERIAL = characterization(1, {
    objects: [DOCUMENT],
    zone: { canvas: CANVAS, shape: {}, source: "own" } as never,
});
const MATERIAL_KEY = `ch:${MATERIAL.id}:-`;

const ALL_KINDS: Item[] = [
    {
        key: ANALYSIS_KEY,
        kind: "analysis",
        analysis: HIT,
        excitation: null,
        files: [],
    },
    {
        key: FILE_KEY,
        kind: "analysis-file",
        analysis: HIT,
        excitation: null,
        file: fileEntry(),
    },
    { key: IMAGING_KEY, kind: "imaging", analysis: HIT, file: imagingEntry() },
    { key: MATERIAL_KEY, kind: "characterization", characterization: MATERIAL },
];

describe("SelectionPanel, links to the document", () => {
    it("links the title of every kind to the address of its document", () => {
        const { wrapper, store } = mountItems(...ALL_KINDS);
        const expected = {
            [ANALYSIS_KEY]: documentHref(
                snapshotOf(store),
                DOCUMENT.id,
                CANVAS,
                {
                    kind: "analysis",
                    id: HIT.id,
                },
            ),
            [MATERIAL_KEY]: documentHref(
                snapshotOf(store),
                DOCUMENT.id,
                CANVAS,
                {
                    kind: "characterization",
                    id: MATERIAL.id,
                },
            ),
        };
        expected[FILE_KEY] = expected[ANALYSIS_KEY];
        expected[IMAGING_KEY] = expected[ANALYSIS_KEY];
        for (const [key, href] of Object.entries(expected)) {
            const link = wrapper.get(`[data-key="${key}"] a.title`);
            expect(link.attributes("href")).toBe(href);
        }
    });

    it("names the link by its title and describes it by one hidden « Open in the document »", () => {
        const { wrapper } = mountItems(...ALL_KINDS);
        const links = wrapper.findAll("a.title");
        const hint = wrapper.findAll("[hidden]");
        expect(hint).toHaveLength(1);
        expect(hint[0].text()).toBe("Open in the document");
        for (const link of links) {
            expect(link.attributes("aria-describedby")).toBe(
                hint[0].attributes("id"),
            );
        }
        expect(links[0].text()).toContain("MS1_f12_XRF_03");
    });

    it("opens the document on its page with the item focused, and says so for a drawer to close", async () => {
        const { wrapper, store } = mountItems(...ALL_KINDS);
        await wrapper
            .get(`[data-key="${MATERIAL_KEY}"] a.title`)
            .trigger("click");
        expect(store.corpusScreen).toBe("document");
        expect(store.document).toEqual({ id: DOCUMENT.id, canvas: CANVAS });
        expect(store.focus).toEqual({
            kind: "characterization",
            id: MATERIAL.id,
        });
        expect(store.folioView).toBe("characterizations");
        expect(wrapper.emitted("navigate")).toHaveLength(1);
    });

    it.each([
        ["Ctrl", { ctrlKey: true }],
        ["Cmd", { metaKey: true }],
        ["Shift", { shiftKey: true }],
        ["Alt", { altKey: true }],
        ["middle", { button: 1 }],
    ])("leaves a %s click to the browser", async (_name, init) => {
        const { wrapper, store } = mountItems(...ALL_KINDS);
        const link = wrapper.get(`[data-key="${ANALYSIS_KEY}"] a.title`);
        let handled = true;
        link.element.addEventListener("click", (event) => {
            handled = event.defaultPrevented;
            event.preventDefault();
        });
        link.element.dispatchEvent(
            new MouseEvent("click", {
                bubbles: true,
                cancelable: true,
                ...init,
            }),
        );
        expect(handled).toBe(false);
        expect(store.corpusScreen).toBe("home");
        expect(wrapper.emitted("navigate")).toBeUndefined();
    });

    it("has no link for a loading row or a material with no document", async () => {
        const onlyComponent = characterization(2, {
            objects: [{ ...DOCUMENT, model: "component" }],
        });
        const { wrapper, store } = mountItems({
            key: `ch:${onlyComponent.id}:-`,
            kind: "characterization",
            characterization: onlyComponent,
        });
        store.addToBasket(`an:${uuid(999)}:-`);
        await nextTick();
        expect(wrapper.find("a").exists()).toBe(false);
        const row = wrapper.get(`[data-key="ch:${onlyComponent.id}:-"]`);
        expect(row.text()).toContain("not placed in a document");
        expect(wrapper.findAll(".pending")).toHaveLength(1);
    });

    it("has no link for a missing item or a row held only by its hint", async () => {
        const pinia = createPinia();
        setActivePinia(pinia);
        const store = useExplorerStore();
        const gone = `an:${uuid(990)}:-`;
        const hinted = `an:${uuid(991)}:-`;
        store.addManyToBasket([gone, hinted]);
        const shared = itemsOf();
        shared.missing.value = new Set([gone]);
        const hints = ref(
            new Map([
                [hinted, { title: label("Zone bleue"), kind: "spectrum" }],
            ]),
        );
        const wrapper = mount(SelectionPanel, {
            global: {
                plugins: [pinia],
                provide: {
                    [SELECTION_ITEMS_KEY as symbol]: () => shared,
                    [SELECTION_HINTS_KEY as symbol]: hints,
                },
            },
        });
        await flushPromises();
        expect(wrapper.find(`[data-key="${gone}"] .gone`).exists()).toBe(true);
        expect(wrapper.find(`[data-key="${hinted}"]`).text()).toContain(
            "Zone bleue",
        );
        expect(wrapper.find("a").exists()).toBe(false);
    });

    it("keeps an analysis with no page linked and says it is not located on a page", () => {
        const unlocated = analysisHit(2);
        const { wrapper } = mountItems({
            key: `an:${unlocated.id}:-`,
            kind: "analysis",
            analysis: unlocated,
            excitation: null,
            files: [],
        });
        const row = wrapper.get(`[data-key="an:${unlocated.id}:-"]`);
        expect(row.find("a.title").attributes("href")).toContain(
            `doc=${uuid(1)}`,
        );
        expect(row.find("a.title").attributes("href")).not.toContain("canvas=");
        expect(row.text()).toContain("not located on a page");
    });

    it("shows the document of a material like that of an analysis", () => {
        const { wrapper } = mountItems(ALL_KINDS[3]);
        expect(wrapper.get(".document").text()).toBe("Manuscript 1");
    });

    it("marks the row whose document and card are open", async () => {
        const { wrapper, store } = mountItems(...ALL_KINDS);
        expect(wrapper.find("[aria-current]").exists()).toBe(false);
        store.openInDocument({
            document: DOCUMENT.id,
            canvas: CANVAS,
            focus: { kind: "analysis", id: HIT.id },
        });
        await nextTick();
        expect(
            wrapper
                .get(`[data-key="${ANALYSIS_KEY}"] a.title`)
                .attributes("aria-current"),
        ).toBe("location");
        expect(
            wrapper
                .get(`[data-key="${MATERIAL_KEY}"] a.title`)
                .attributes("aria-current"),
        ).toBeUndefined();
    });

    it("puts the link before the remove button in the tab order, and the button does not navigate", async () => {
        const { wrapper, store } = mountItems(ALL_KINDS[0]);
        const focusable = [
            ...wrapper
                .get(`[data-key="${ANALYSIS_KEY}"]`)
                .element.querySelectorAll<HTMLElement>("a[href], button"),
        ];
        expect(focusable.map((element) => element.tagName)).toEqual([
            "A",
            "BUTTON",
        ]);
        expect(focusable.every((element) => element.tabIndex === 0)).toBe(true);
        await wrapper.get(".remove").trigger("click");
        expect(store.corpusScreen).toBe("home");
        expect(store.basket).toHaveLength(0);
        expect(wrapper.emitted("navigate")).toBeUndefined();
    });
});
