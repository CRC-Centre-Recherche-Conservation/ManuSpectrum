import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import OnThisPage from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/OnThisPage.vue";

import { techniqueStyles } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import {
    annotation,
    characterization,
    label,
    uuid,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

function mountList(props: Record<string, unknown>) {
    const annotations =
        (props.annotations as ReturnType<typeof annotation>[]) ?? [];
    return mount(OnThisPage, {
        props: {
            annotations,
            unlocated: [],
            characterizations: [],
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
            annotation(2, { technique: valueRef("t:fors", "FORS") }),
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

    it("lists the identified materials of the page", async () => {
        const summary = characterization(1);
        const wrapper = mountList({ characterizations: [summary] });
        await wrapper.find(".materials button").trigger("click");
        expect(wrapper.emitted("select")?.[0]).toEqual([
            { kind: "characterization", id: summary.id },
        ]);
    });

    it("says when the page has no analysis", () => {
        expect(mountList({}).text()).toContain(
            "No published analysis on this page.",
        );
    });
});
