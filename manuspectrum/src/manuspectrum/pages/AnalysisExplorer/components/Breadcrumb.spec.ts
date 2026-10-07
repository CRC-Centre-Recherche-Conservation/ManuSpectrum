import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import Breadcrumb from "@/manuspectrum/pages/AnalysisExplorer/components/Breadcrumb.vue";

const ITEMS = [
    { id: "corpus", label: "Whole corpus" },
    { id: "results", label: "Results · 3 documents" },
    { id: "document", label: "Avranches, Ms. 59" },
];

function mountTrail() {
    return mount(Breadcrumb, {
        props: { items: ITEMS },
    });
}

describe("Breadcrumb", () => {
    it("is a named nav holding an ordered list", () => {
        const nav = mountTrail().get("nav");
        expect(nav.attributes("aria-label")).toBe("Breadcrumb");
        expect(nav.findAll("ol > li")).toHaveLength(3);
    });

    it("marks the last item as the current page and makes it no button", () => {
        const items = mountTrail().findAll("li");
        expect(items[2].attributes("aria-current")).toBeUndefined();
        const last = items[2].get("[aria-current='page']");
        expect(last.text()).toBe("Avranches, Ms. 59");
        expect(last.element.tagName).not.toBe("BUTTON");
        expect(items[0].find("[aria-current]").exists()).toBe(false);
    });

    it("emits go with the id of an earlier item", async () => {
        const wrapper = mountTrail();
        const buttons = wrapper.findAll("button");
        expect(buttons.map((button) => button.text())).toEqual([
            "Whole corpus",
            "Results · 3 documents",
        ]);
        await buttons[1].trigger("click");
        await buttons[0].trigger("click");
        expect(wrapper.emitted("go")).toEqual([["results"], ["corpus"]]);
    });

    it("hides its separators from assistive technology", () => {
        const separators = mountTrail().findAll("svg.separator");
        expect(separators).toHaveLength(2);
        expect(separators[0].attributes("aria-hidden")).toBe("true");
    });
});
