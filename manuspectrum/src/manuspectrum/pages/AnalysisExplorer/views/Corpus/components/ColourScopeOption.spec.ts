import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import ColourScopeOption from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/ColourScopeOption.vue";

function mountOption(scope: "all" | "part" | "material" = "all") {
    return mount(ColourScopeOption, { props: { scope } });
}

describe("ColourScopeOption", () => {
    it("is folded to its disclosure button until opened", async () => {
        const wrapper = mountOption();
        const button = wrapper.find("button.disclosure");
        expect(button.text()).toContain("Where the colour is recorded");
        expect(button.attributes("aria-expanded")).toBe("false");
        expect(wrapper.find("fieldset").element.style.display).toBe("none");
        await button.trigger("click");
        expect(button.attributes("aria-expanded")).toBe("true");
        expect(wrapper.find("fieldset").element.style.display).toBe("");
        expect(button.attributes("aria-controls")).toBe(
            wrapper.find("fieldset").attributes("id"),
        );
        await button.trigger("click");
        expect(button.attributes("aria-expanded")).toBe("false");
    });

    it("offers three radios in a named group, checked on the scope in force", async () => {
        const wrapper = mountOption("part");
        await wrapper.find("button.disclosure").trigger("click");
        expect(wrapper.find("fieldset legend").text()).toBe(
            "Where the colour is recorded",
        );
        const radios = wrapper.findAll<HTMLInputElement>("input[type=radio]");
        expect(
            wrapper.findAll(".option .text").map((label) => label.text()),
        ).toEqual([
            "Everywhere (default)",
            "Studied component",
            "Identified material",
        ]);
        expect(radios.map((radio) => radio.element.checked)).toEqual([
            false,
            true,
            false,
        ]);
        expect(
            new Set(radios.map((radio) => radio.attributes("name"))).size,
        ).toBe(1);
    });

    it("describes each choice by a help tip the radio points to", async () => {
        const wrapper = mountOption();
        await wrapper.find("button.disclosure").trigger("click");
        const helps = wrapper
            .findAll<HTMLInputElement>("input[type=radio]")
            .map((radio) => {
                const id = radio.attributes("aria-describedby") ?? "";
                return wrapper.find(`#${id}`).text();
            });
        expect(helps).toEqual([
            "Colour of the component or of an identified material",
            "Colours described on the studied component, even without analysis",
            "Colour of the zone where a material was identified from the analyses",
        ]);
    });

    it("emits the scope chosen", async () => {
        const wrapper = mountOption();
        await wrapper.find("button.disclosure").trigger("click");
        await wrapper.findAll("input[type=radio]")[2].setValue(true);
        await wrapper.findAll("input[type=radio]")[1].setValue(true);
        expect(wrapper.emitted("change")).toEqual([["material"], ["part"]]);
    });
});
