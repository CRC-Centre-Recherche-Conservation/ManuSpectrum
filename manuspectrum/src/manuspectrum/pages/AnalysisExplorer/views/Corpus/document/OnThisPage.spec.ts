import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import OnThisPage from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/OnThisPage.vue";

import { techniqueStyles } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import {
    annotation,
    characterization,
    label,
    sample,
    technique,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

function mountList(props: Record<string, unknown>) {
    const annotations =
        (props.annotations as ReturnType<typeof annotation>[]) ?? [];
    return mount(OnThisPage, {
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

    it("marks the analyses outside the filters", () => {
        const wrapper = mountList({
            annotations: [annotation(1, { match: false })],
        });
        expect(wrapper.find(".technique li").text()).toContain(
            "outside the filters",
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
