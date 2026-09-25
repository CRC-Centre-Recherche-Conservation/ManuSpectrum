import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it } from "vitest";
import { defineComponent, h, ref, shallowRef } from "vue";

import AnalysisCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/AnalysisCard.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisPayload,
    characterization,
    fileEntry,
    label,
    uuid,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { AnalysisPayload } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestStatus } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

function mountCard(
    payload: AnalysisPayload | null,
    status: RequestStatus = "ready",
    analysisId: string = payload?.id ?? uuid(101),
) {
    const pinia = createPinia();
    setActivePinia(pinia);
    const handle = {
        status: ref(status),
        data: shallowRef(payload),
        retry: () => undefined,
    };
    const wrapper = mount(AnalysisCard, {
        props: { handle, analysisId },
        global: { plugins: [pinia], stubs: { SpectrumPreview: true } },
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

    it("marks the default licence", () => {
        const file = fileEntry();
        file.license = { ...file.license, isDefault: true };
        const { wrapper } = mountCard(analysisPayload({ files: [file] }));
        expect(wrapper.find(".licence").text()).toContain("default licence");
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

    it("adds the analysis to the Selection by its spectrum", async () => {
        const { wrapper, store } = mountCard(analysisPayload());
        await wrapper
            .find(".card-head .add-to-selection button")
            .trigger("click");
        expect(store.basket[0].key).toBe(`af:${uuid(101)}:${uuid(700)}`);
    });

    it("opens the full record, a page of this site, in a new tab", () => {
        const { wrapper } = mountCard(analysisPayload());
        const record = wrapper.find("a.record");
        expect(record.attributes("href")).toBe(`/en/report/${uuid(101)}`);
        expect(record.attributes("target")).toBe("_blank");
        expect(record.attributes("rel")).toBe("noopener");
        expect(record.text()).toContain("(new tab)");
    });

    it("asks to be closed", async () => {
        const { wrapper } = mountCard(analysisPayload());
        await wrapper.find(".card-head .close").trigger("click");
        expect(wrapper.emitted("close")).toHaveLength(1);
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
            retry: () => undefined,
        };
        const wrapper = mount(
            defineComponent(() => () => [
                h(AnalysisCard, { handle, analysisId: uuid(101) }),
                h(AnalysisCard, { handle, analysisId: uuid(101) }),
            ]),
            { global: { plugins: [pinia], stubs: { SpectrumPreview: true } } },
        );
        const sections = wrapper.findAll(".conditions");
        const ids = sections.map((section) =>
            section.find("h4").attributes("id"),
        );
        expect(ids[0]).toBeTruthy();
        expect(ids[0]).not.toBe(ids[1]);
        expect(sections[0].attributes("aria-labelledby")).toBe(ids[0]);
    });
});
