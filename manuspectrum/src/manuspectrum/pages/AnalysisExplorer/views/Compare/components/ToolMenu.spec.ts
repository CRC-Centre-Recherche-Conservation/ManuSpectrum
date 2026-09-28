import { afterEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import ToolMenu from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ToolMenu.vue";

import type { VueWrapper } from "@vue/test-utils";

let wrapper: VueWrapper | null = null;

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
});

function mountMenu(props: Record<string, unknown> = {}): VueWrapper {
    wrapper = mount(ToolMenu, {
        attachTo: document.body,
        props: {
            offered: ["coverage", "periodic", "folio"],
            status: "ready",
            ...props,
        },
    });
    return wrapper;
}

function items(view: VueWrapper) {
    return view.findAll('[role="menuitem"]');
}

describe("ToolMenu", () => {
    it("is a closed menu button until pressed", async () => {
        const view = mountMenu();
        const button = view.find("button.tool-menu-button");
        expect(button.text()).toBe("+ Tool");
        expect(button.attributes("aria-haspopup")).toBe("menu");
        expect(button.attributes("aria-expanded")).toBe("false");
        expect(view.find('[role="menu"]').exists()).toBe(false);
        await button.trigger("click");
        expect(button.attributes("aria-expanded")).toBe("true");
        expect(view.find('[role="menu"]').attributes("aria-labelledby")).toBe(
            button.attributes("id"),
        );
        expect(items(view).map((item) => item.text())).toEqual([
            "Coverage matrix",
            "Periodic table",
            "Folio image",
        ]);
        expect(document.activeElement).toBe(items(view)[0].element);
    });

    it("moves through the entries with the arrows and closes on Escape", async () => {
        const view = mountMenu();
        const button = view.find("button.tool-menu-button");
        await button.trigger("keydown", { key: "ArrowUp" });
        expect(document.activeElement).toBe(items(view)[2].element);
        await view.find('[role="menu"]').trigger("keydown", {
            key: "ArrowDown",
        });
        expect(document.activeElement).toBe(items(view)[0].element);
        await view.find('[role="menu"]').trigger("keydown", { key: "End" });
        expect(document.activeElement).toBe(items(view)[2].element);
        await view.find('[role="menu"]').trigger("keydown", { key: "Home" });
        expect(document.activeElement).toBe(items(view)[0].element);
        await view.find('[role="menu"]').trigger("keydown", {
            key: "Escape",
        });
        expect(view.find('[role="menu"]').exists()).toBe(false);
        expect(document.activeElement).toBe(button.element);
    });

    it("emits the tool chosen, closes and gives the focus back", async () => {
        const view = mountMenu();
        await view.find("button.tool-menu-button").trigger("click");
        await items(view)[1].trigger("click");
        expect(view.emitted("choose")).toEqual([[{ kind: "periodic" }]]);
        expect(view.find('[role="menu"]').exists()).toBe(false);
        expect(document.activeElement).toBe(
            view.find("button.tool-menu-button").element,
        );
    });

    it("says the Selection is being read, and offers no tool yet", async () => {
        const view = mountMenu({ offered: null, status: "loading" });
        await view.find("button.tool-menu-button").trigger("click");
        expect(items(view).map((item) => item.text())).toEqual([
            "Reading the Selection…",
        ]);
        expect(items(view)[0].attributes("aria-disabled")).toBe("true");
    });

    it("offers a retry when the synthesis failed", async () => {
        const view = mountMenu({ offered: null, status: "error" });
        await view.find("button.tool-menu-button").trigger("click");
        await items(view)[0].trigger("click");
        expect(view.emitted("retry")).toHaveLength(1);
    });

    it("says when the Selection has nothing for a tool", async () => {
        const view = mountMenu({ offered: [] });
        await view.find("button.tool-menu-button").trigger("click");
        expect(items(view).map((item) => item.text())).toEqual([
            "No tool for this Selection",
        ]);
    });

    it("closes when the focus leaves it", async () => {
        const view = mountMenu();
        await view.find("button.tool-menu-button").trigger("click");
        await view.find('[role="menu"]').trigger("keydown", { key: "Tab" });
        expect(view.find('[role="menu"]').exists()).toBe(false);
    });

    it("gives the focus to the first entry when the entries change while it is open", async () => {
        const view = mountMenu({ offered: null, status: "loading" });
        await view.find("button.tool-menu-button").trigger("click");
        await view.setProps({
            offered: ["periodic", "folio"],
            status: "ready",
        });
        expect(document.activeElement).toBe(items(view)[0].element);
        expect(items(view)[0].text()).toBe("Periodic table");
    });
});
