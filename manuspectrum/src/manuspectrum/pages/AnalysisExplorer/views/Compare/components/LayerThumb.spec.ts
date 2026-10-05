import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import LayerThumb from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LayerThumb.vue";

import { LAYER_DRAG_TYPE } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-drag.ts";

const SERVICE = "https://iiif.example/image/pb";

function thumb(props: Record<string, unknown> = {}) {
    return mount(LayerThumb, {
        props: {
            canvas: "c1",
            label: "map_Cu_lim255",
            service: SERVICE,
            tag: null,
            panes: [],
            inStack: false,
            stop: false,
            ...props,
        },
    });
}

describe("LayerThumb", () => {
    it("asks a lazy small image of the service and writes the stored label in full as its title", () => {
        const view = thumb();
        const image = view.find("img");
        expect(image.attributes("src")).toBe(
            `${SERVICE}/full/!120,150/0/default.jpg`,
        );
        expect(image.attributes("loading")).toBe("lazy");
        expect(image.attributes("referrerpolicy")).toBe("no-referrer");
        expect(view.find(".label").attributes("title")).toBe("map_Cu_lim255");
    });

    it("turns into a flat with the label once the image fails, without asking another size", async () => {
        const view = thumb();
        await view.find("img").trigger("error");
        expect(view.find("img").exists()).toBe(false);
        expect(view.find(".flat").text()).toContain("map_Cu_lim255");
    });

    it("shows the tag as a badge only when it differs from the label", () => {
        expect(thumb({ tag: "Cu" }).find(".tag-badge").text()).toBe("Cu");
        expect(
            thumb({ tag: "map_cu_lim255" }).find(".tag-badge").exists(),
        ).toBe(false);
        expect(thumb().find(".tag-badge").exists()).toBe(false);
    });

    it("lists the panes holding the canvas and marks the stack", () => {
        const view = thumb({ panes: ["A", "C"], inStack: true });
        expect(
            view.findAll(".pane-badge").map((badge) => badge.text()),
        ).toEqual(["A", "C"]);
        expect(view.classes()).toContain("in-stack");
    });

    it("emits pick on click and carries its canvas id on drag", async () => {
        const view = thumb();
        await view.trigger("click");
        expect(view.emitted("pick")).toHaveLength(1);
        const data = new Map<string, string>();
        await view.trigger("dragstart", {
            dataTransfer: {
                setData: (type: string, value: string) => data.set(type, value),
                effectAllowed: "",
            },
        });
        expect(data.get(LAYER_DRAG_TYPE)).toBe("c1");
    });

    it("holds the tab stop only when it is the stop", () => {
        expect(thumb({ stop: true }).attributes("tabindex")).toBe("0");
        expect(thumb().attributes("tabindex")).toBe("-1");
    });
});
