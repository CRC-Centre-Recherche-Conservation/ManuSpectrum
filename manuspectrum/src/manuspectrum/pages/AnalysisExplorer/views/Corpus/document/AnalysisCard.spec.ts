import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, ref, shallowRef } from "vue";

import type { Ref } from "vue";

import CitationBlock from "@/manuspectrum/pages/AnalysisExplorer/components/CitationBlock.vue";
import CopyButton from "@/manuspectrum/pages/AnalysisExplorer/components/CopyButton.vue";
import AnalysisCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/AnalysisCard.vue";

import {
    CITE_OPEN_KEY,
    MIRADOR_URL_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisPayload,
    characterization,
    contentStateLink,
    fileEntry,
    label,
    uuid,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { AnalysisPayload } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestStatus } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

enableAutoUnmount(afterEach);

const MIRADOR = "https://viewer.example/mirador/";
const IIIF_HELP =
    "IIIF link to this zone: paste it into a IIIF viewer (Mirador…) to open the folio centred on this zone.";
const IIIF_HELP_DELAY_MS = 500;

interface CardExtras {
    feature?: string | null;
    mirador?: string;
    attach?: boolean;
    citeOpen?: Ref<boolean>;
}

function mountCard(
    payload: AnalysisPayload | null,
    status: RequestStatus = "ready",
    analysisId: string = payload?.id ?? uuid(101),
    { feature = null, mirador = "", attach = false, citeOpen }: CardExtras = {},
) {
    const pinia = createPinia();
    setActivePinia(pinia);
    const handle = {
        status: ref(status),
        data: shallowRef(payload),
        loaded: ref(payload ? analysisId : null),
        retry: () => undefined,
    };
    const wrapper = mount(AnalysisCard, {
        props: { handle, analysisId, feature },
        attachTo: attach ? document.body : undefined,
        global: {
            plugins: [pinia, PrimeVue],
            stubs: { SpectrumPreview: true },
            provide: {
                [MIRADOR_URL_KEY as symbol]: mirador,
                ...(citeOpen ? { [CITE_OPEN_KEY as symbol]: citeOpen } : {}),
            },
        },
    });
    return { wrapper, store: useExplorerStore() };
}

describe("AnalysisCard", () => {
    it("shows the readable file with its raw pair beside it", () => {
        const readable = fileEntry({ id: uuid(8), pairedWith: uuid(9) });
        const raw = fileEntry({
            id: uuid(9),
            name: "X01_f1v.mca",
            role: "raw",
            dataKind: "file",
            format: "",
            size: 42_000,
            pairedWith: uuid(8),
            previewUrl: null,
        });
        const { wrapper } = mountCard(
            analysisPayload({ files: [readable, raw] }),
        );
        const row = wrapper.find(`[data-file="${uuid(8)}"]`);
        expect(row.text()).toContain("raw instrument");
        expect(row.text()).toContain(".mca");
        expect(row.find("a.raw").attributes("href")).toBe(raw.downloadUrl);
    });

    it("writes a file and its raw pair with an unsafe address as plain text", () => {
        const readable = fileEntry({
            id: uuid(8),
            name: "X01_f1v.csv",
            pairedWith: uuid(9),
            downloadUrl: "javascript:alert(1)",
        });
        const raw = fileEntry({
            id: uuid(9),
            name: "X01_f1v",
            role: "raw",
            dataKind: "file",
            format: "mca",
            pairedWith: uuid(8),
            downloadUrl: "javascript:alert(2)",
            previewUrl: null,
        });
        const { wrapper } = mountCard(
            analysisPayload({ files: [readable, raw] }),
        );
        const row = wrapper.find(`[data-file="${uuid(8)}"]`);
        expect(row.find("a").exists()).toBe(false);
        expect(row.find("span.file-name").text()).toBe("X01_f1v.csv");
        expect(row.find("span.raw").text()).toContain("raw instrument · mca");
    });

    it("puts a raw file without a readable version under « not in a chart »", () => {
        const raw = fileEntry({
            id: uuid(9),
            name: "lone.asd",
            role: "raw",
            dataKind: "file",
            previewUrl: null,
        });
        const { wrapper } = mountCard(analysisPayload({ files: [raw] }));
        expect(wrapper.find(".not-in-chart").text()).toContain("lone.asd");
        expect(wrapper.find(".not-in-chart").text()).toContain(
            "Download the raw file",
        );
        expect(wrapper.find(".not-in-chart .download-only").text()).toBe(
            "Raw instrument files are offered for download only: the charts read their text exports, converted upstream.",
        );
    });

    it("says nothing of instrument files when only other files are not in a chart", () => {
        const other = fileEntry({
            id: uuid(9),
            name: "report.pdf",
            role: "other",
            dataKind: "file",
            previewUrl: null,
        });
        const { wrapper } = mountCard(analysisPayload({ files: [other] }));
        expect(wrapper.find(".not-in-chart").text()).toContain(
            "Download the file",
        );
        expect(wrapper.find(".not-in-chart .download-only").exists()).toBe(
            false,
        );
    });

    it("groups the measurement conditions by type and puts untyped ones under Note", () => {
        const conditions = [
            {
                type: valueRef("aat:config", "configuration"),
                html: "<p>260 µm</p>",
                lang: "en",
            },
            { type: null, html: "<p>free text</p>", lang: "fr" },
        ];
        const { wrapper } = mountCard(analysisPayload({ conditions }));
        const text = wrapper.find(".conditions").text();
        expect(text).toContain("configuration");
        expect(text).toContain("Note");
        expect(text).toContain("free text");
    });

    it("says when no measurement condition is given", () => {
        const { wrapper } = mountCard(analysisPayload({ conditions: [] }));
        expect(wrapper.find(".conditions").text()).toContain("Not provided");
    });

    it("shows no licence when the file states none", () => {
        const file = fileEntry();
        file.license = { ...file.license, isDefault: true };
        const { wrapper } = mountCard(analysisPayload({ files: [file] }));
        expect(wrapper.find(".licence").exists()).toBe(false);
        expect(wrapper.text()).not.toContain("Project licence");
    });

    it("credits the rights holder and writes a licence without a safe address as plain text", () => {
        const file = fileEntry();
        file.license = {
            ...file.license,
            url: "javascript:alert(1)",
            attribution: "CRC",
        };
        const credited = fileEntry();
        credited.license = { ...credited.license, attribution: "© BnF" };

        const unsafe = mountCard(analysisPayload({ files: [file] })).wrapper;
        expect(unsafe.find(".licence a").exists()).toBe(false);
        expect(unsafe.find(".licence").text()).toContain(
            file.license.label.value,
        );
        expect(unsafe.find(".attribution").text()).toBe("© CRC");

        const kept = mountCard(analysisPayload({ files: [credited] })).wrapper;
        expect(kept.find(".attribution").text()).toBe("© BnF");
    });

    it("leaves out a condition title that repeats the section's", () => {
        const single = mountCard(
            analysisPayload({
                conditions: [
                    {
                        type: valueRef("aat:cond", "conditions"),
                        html: "<p>40 kV</p>",
                        lang: "en",
                    },
                ],
            }),
        ).wrapper;
        expect(single.find(".conditions dt").exists()).toBe(false);
        expect(single.find(".conditions").text()).toContain("40 kV");
    });

    it("adds the whole analysis from its head and never a single file", () => {
        const { wrapper } = mountCard(analysisPayload());
        const head = wrapper.find(".card-head .add-to-selection button");
        expect(head.text()).toBe("+ Selection");
        expect(head.attributes("aria-label")).toBe(
            "Add the analysis MS1_f12_XRF_03 to the Selection",
        );
        expect(wrapper.findAll(".add-to-selection")).toHaveLength(1);
        expect(wrapper.find(".files .add-to-selection").exists()).toBe(false);
    });

    it("links a DOI dataset to its resolver and writes an unsafe address as plain text", () => {
        const doi = mountCard(
            analysisPayload({
                dataset: { url: "10.5281/zenodo.1", isDoi: true, label: null },
            }),
        ).wrapper;
        expect(doi.find(".details a").attributes("href")).toBe(
            "https://doi.org/10.5281/zenodo.1",
        );
        const unsafe = mountCard(
            analysisPayload({
                dataset: {
                    url: "javascript:alert(1)",
                    isDoi: false,
                    label: "Data",
                },
            }),
        ).wrapper;
        expect(unsafe.find(".details a").exists()).toBe(false);
        expect(unsafe.find(".details").text()).toContain("Data");
    });

    it("opens the identified material it supports", async () => {
        const summary = characterization(1, {
            name: label("Vermilion, f. 1v"),
        });
        const { wrapper, store } = mountCard(
            analysisPayload({ evidenceOf: [summary] }),
        );
        await wrapper.find(".evidence-of button").trigger("click");
        expect(store.focus).toEqual({
            kind: "characterization",
            id: summary.id,
        });
    });

    it("adds the whole analysis to the Selection", async () => {
        const { wrapper, store } = mountCard(analysisPayload());
        await wrapper
            .find(".card-head .add-to-selection button")
            .trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual([
            `an:${uuid(101)}:-`,
        ]);
    });

    it("adds an analysis with nothing to show all the same", async () => {
        const { wrapper, store } = mountCard(analysisPayload({ files: [] }));
        await wrapper
            .find(".card-head .add-to-selection button")
            .trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual([
            `an:${uuid(101)}:-`,
        ]);
    });

    it("opens the full record, a page of this site, in a new tab", () => {
        const { wrapper } = mountCard(analysisPayload());
        const record = wrapper.find("a.record");
        expect(record.attributes("href")).toBe(`/en/report/${uuid(101)}`);
        expect(record.attributes("target")).toBe("_blank");
        expect(record.attributes("rel")).toBe("noopener");
        expect(record.text()).toContain("(new tab)");
    });

    it("closes through an icon button named « Close the card », described by Escape", async () => {
        const { wrapper } = mountCard(analysisPayload());
        const button = wrapper.find("button.close");
        const named = (attribute: string) =>
            wrapper.find(`[id="${button.attributes(attribute)}"]`).text();

        expect(button.text()).toBe("");
        expect(named("aria-labelledby")).toBe("Close the card");
        expect(named("aria-describedby")).toBe("Escape");
        await button.trigger("click");
        expect(wrapper.emitted("close")).toHaveLength(1);
    });

    it("asks to be closed", async () => {
        const { wrapper } = mountCard(analysisPayload());
        await wrapper.find(".card-head button.close").trigger("click");
        expect(wrapper.emitted("close")).toHaveLength(1);
    });

    it("puts Close right after the heading, whatever the header holds", () => {
        const { wrapper } = mountCard(analysisPayload());
        expect(wrapper.find(".card-head .name + .icon-button").exists()).toBe(
            true,
        );
    });

    it("marks a draft analysis", () => {
        const { wrapper } = mountCard(analysisPayload({ unpublished: true }));
        expect(wrapper.find(".card-head").text()).toContain("Draft");
    });

    it("shows the unavailable state for a refused analysis", () => {
        const { wrapper } = mountCard(null, "unavailable");
        expect(wrapper.text()).toContain("This item is not available.");
    });

    it("shows nothing of the previous analysis while the next one loads", () => {
        const { wrapper } = mountCard(
            analysisPayload({ name: label("Previous analysis") }),
            "loading",
            uuid(102),
        );
        expect(wrapper.text()).not.toContain("Previous analysis");
        expect(wrapper.find(".add-to-selection").exists()).toBe(false);
        expect(wrapper.find(".card-head h3").text()).toBe(
            "Loading the analysis…",
        );
    });

    it("keeps its heading element from loading to loaded, so a focus on it stays", async () => {
        const { wrapper } = mountCard(null, "loading", uuid(101));
        const heading = wrapper.find(".card-head h3").element;
        const handle = wrapper.props("handle") as {
            data: { value: AnalysisPayload | null };
            status: { value: RequestStatus };
        };
        handle.data.value = analysisPayload();
        handle.status.value = "ready";
        await wrapper.vm.$nextTick();
        expect(wrapper.find(".card-head h3").element).toBe(heading);
        expect(wrapper.find(".card-head h3").text()).toBe("MS1_f12_XRF_03");
    });

    it("gives its section headings ids of its own", () => {
        const pinia = createPinia();
        setActivePinia(pinia);
        const handle = {
            status: ref<RequestStatus>("ready"),
            data: shallowRef<AnalysisPayload | null>(analysisPayload()),
            loaded: ref<string | null>(uuid(101)),
            retry: () => undefined,
        };
        const wrapper = mount(
            defineComponent(() => () => [
                h(AnalysisCard, { handle, analysisId: uuid(101) }),
                h(AnalysisCard, { handle, analysisId: uuid(101) }),
            ]),
            {
                global: {
                    plugins: [pinia, PrimeVue],
                    stubs: { SpectrumPreview: true },
                },
            },
        );
        const sections = wrapper.findAll(".conditions");
        const ids = sections.map((section) =>
            section.find("h4").attributes("id"),
        );
        expect(ids[0]).toBeTruthy();
        expect(ids[0]).not.toBe(ids[1]);
        expect(sections[0].attributes("aria-labelledby")).toBe(ids[0]);
    });

    it("shows the citation of the analysis", () => {
        const payload = analysisPayload();
        const { wrapper } = mountCard(payload);

        const block = wrapper.findComponent(CitationBlock);
        expect(block.exists()).toBe(true);
        expect(block.props("citation")).toEqual(payload.citation);
        expect(wrapper.find(".cite").text()).toContain("Cite");
    });

    it("copies the data availability statement of the analysis", () => {
        const payload = analysisPayload();
        const { wrapper } = mountCard(payload);

        const copy = wrapper
            .findAllComponents(CopyButton)
            .find(
                (button) =>
                    button.props("label") ===
                    "Copy the data availability statement",
            );
        expect(copy?.props("text")).toBe(payload.availability);
    });

    function iiifCopy(wrapper: ReturnType<typeof mountCard>["wrapper"]) {
        return wrapper
            .findAllComponents(CopyButton)
            .find((button) => button.props("label") === "Copy the IIIF link");
    }

    it("copies the IIIF link of the focused zone", async () => {
        const focused = contentStateLink(uuid(101), uuid(902));
        const payload = analysisPayload({
            contentStates: [contentStateLink(uuid(101), uuid(901)), focused],
        });
        const { wrapper } = mountCard(payload, "ready", payload.id, {
            feature: uuid(902),
        });
        await flushPromises();

        expect(iiifCopy(wrapper)?.props("text")).toBe(focused.url);
    });

    it("offers the IIIF link alone, marked with a link icon", async () => {
        const payload = analysisPayload();
        const { wrapper } = mountCard(payload, "ready", payload.id, {
            feature: uuid(901),
        });
        await flushPromises();

        const links = wrapper.find(".iiif");
        expect(links.findAll("a")).toHaveLength(0);
        expect(links.text()).not.toContain("Download");
        const icon = iiifCopy(wrapper)?.find("svg.link-icon");
        expect(icon?.exists()).toBe(true);
        expect(icon?.attributes("aria-hidden")).toBe("true");
    });

    it("describes the IIIF link with its help, one hidden tooltip node", async () => {
        const payload = analysisPayload();
        const { wrapper } = mountCard(payload, "ready", payload.id, {
            feature: uuid(901),
            attach: true,
        });
        await flushPromises();

        const button = iiifCopy(wrapper)!;
        const description = wrapper.find(
            `#${button.attributes("aria-describedby")}`,
        );
        expect(description.text()).toBe(IIIF_HELP);
        expect(description.attributes("hidden")).toBeDefined();
        expect(description.attributes("role")).toBe("tooltip");
        const copies = [
            ...document.body.querySelectorAll('[role="tooltip"]'),
        ].filter((tooltip) => tooltip.textContent === IIIF_HELP);
        expect(copies).toHaveLength(1);
    });

    describe("IIIF link help", () => {
        const shown = () =>
            document.body.querySelector('[role="tooltip"]:not([hidden])');
        const pointer = (type: string) =>
            Object.assign(new Event(type, { bubbles: true }), {
                pointerType: "mouse",
            });

        async function mountLinked() {
            const payload = analysisPayload();
            const { wrapper } = mountCard(payload, "ready", payload.id, {
                feature: uuid(901),
                attach: true,
            });
            await flushPromises();
            const button = iiifCopy(wrapper)!.element as HTMLElement;
            return { wrapper, button, area: button.parentElement! };
        }

        beforeEach(() => {
            vi.useFakeTimers();
        });

        afterEach(() => {
            vi.useRealTimers();
        });

        it("shows after the delay on keyboard focus, not a millisecond before", async () => {
            const { wrapper, button } = await mountLinked();
            button.focus();

            vi.advanceTimersByTime(IIIF_HELP_DELAY_MS - 1);
            await wrapper.vm.$nextTick();
            expect(shown()).toBeNull();
            vi.advanceTimersByTime(1);
            await wrapper.vm.$nextTick();
            expect(shown()?.textContent).toBe(IIIF_HELP);
        });

        it("shows after the delay on hover and stays while the pointer moves onto it", async () => {
            const { wrapper, area } = await mountLinked();
            area.dispatchEvent(pointer("pointerenter"));

            vi.advanceTimersByTime(IIIF_HELP_DELAY_MS - 1);
            await wrapper.vm.$nextTick();
            expect(shown()).toBeNull();
            vi.advanceTimersByTime(1);
            await wrapper.vm.$nextTick();
            const tip = shown()!;
            expect(tip.textContent).toBe(IIIF_HELP);

            expect(area.contains(tip)).toBe(true);
            tip.dispatchEvent(pointer("pointerenter"));
            vi.advanceTimersByTime(IIIF_HELP_DELAY_MS);
            await wrapper.vm.$nextTick();
            expect(shown()).toBe(tip);
        });

        it("shows nothing after a click", async () => {
            const { wrapper, button, area } = await mountLinked();
            area.dispatchEvent(pointer("pointerenter"));
            button.dispatchEvent(pointer("pointerdown"));
            button.focus();
            button.click();

            vi.advanceTimersByTime(IIIF_HELP_DELAY_MS * 4);
            await wrapper.vm.$nextTick();
            expect(shown()).toBeNull();
        });

        it("hides on Escape pressed outside the link", async () => {
            const { wrapper, area } = await mountLinked();
            area.dispatchEvent(pointer("pointerenter"));
            vi.advanceTimersByTime(IIIF_HELP_DELAY_MS);
            await wrapper.vm.$nextTick();
            expect(shown()).not.toBeNull();

            document.body.dispatchEvent(
                new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
            );
            await wrapper.vm.$nextTick();
            expect(shown()).toBeNull();
        });
    });

    it("opens Mirador with the content state when a viewer is set", async () => {
        const payload = analysisPayload();
        const state = payload.contentStates[0];
        const { wrapper } = mountCard(payload, "ready", payload.id, {
            feature: state.feature,
            mirador: MIRADOR,
        });
        await flushPromises();

        const href = wrapper.find("a.mirador").attributes("href") as string;
        expect(href.startsWith(MIRADOR)).toBe(true);
        expect(new URL(href).searchParams.get("iiif-content")).toBe(state.url);
        expect(iiifCopy(wrapper)?.props("text")).toBe(href);

        const without = mountCard(payload, "ready", payload.id, {
            feature: state.feature,
        });
        await flushPromises();
        expect(without.wrapper.find("a.mirador").exists()).toBe(false);
    });

    it("offers no IIIF link for an unlocated analysis", async () => {
        const unlocated = analysisPayload({ contentStates: [] });
        for (const [payload, feature] of [
            [analysisPayload(), null],
            [unlocated, uuid(901)],
        ] as const) {
            const { wrapper } = mountCard(payload, "ready", undefined, {
                feature,
                mirador: MIRADOR,
            });
            await flushPromises();

            expect(iiifCopy(wrapper)).toBeUndefined();
            expect(wrapper.find("a.mirador").exists()).toBe(false);
        }
    });

    it("keeps the dataset link next to the citation", () => {
        const payload = analysisPayload({
            dataset: {
                url: "https://doi.org/10.48579/PRO/ZEEJTH",
                isDoi: true,
                label: "Parchment data",
            },
        });
        const { wrapper } = mountCard(payload);

        const dataset = wrapper.find(
            'a[href="https://doi.org/10.48579/PRO/ZEEJTH"]',
        );
        expect(dataset.exists()).toBe(true);
        expect(wrapper.findComponent(CitationBlock).exists()).toBe(true);
    });

    it("folds the citation by default and keeps its copy button in view", () => {
        const payload = analysisPayload();
        const { wrapper } = mountCard(payload, "ready", payload.id, {
            attach: true,
        });
        const toggle = wrapper.get(".cite button.toggle");
        expect(toggle.attributes("aria-expanded")).toBe("false");
        expect(wrapper.get(".cite .content").isVisible()).toBe(false);
        const copy = wrapper.get(".cite .head").findComponent(CopyButton);
        expect(copy.props("text")).toBe(payload.citation.text);
        expect(copy.isVisible()).toBe(true);
    });

    it("unfolds the citation and records it in the state the shell keeps", async () => {
        const payload = analysisPayload();
        const citeOpen = ref(false);
        const { wrapper } = mountCard(payload, "ready", payload.id, {
            attach: true,
            citeOpen,
        });
        await wrapper.get(".cite button.toggle").trigger("click");
        expect(citeOpen.value).toBe(true);
        expect(wrapper.get(".cite .content").isVisible()).toBe(true);
    });

    it("opens the citation when the shell says so", () => {
        const payload = analysisPayload();
        const { wrapper } = mountCard(payload, "ready", payload.id, {
            attach: true,
            citeOpen: ref(true),
        });
        expect(
            wrapper.get(".cite button.toggle").attributes("aria-expanded"),
        ).toBe("true");
    });
});
