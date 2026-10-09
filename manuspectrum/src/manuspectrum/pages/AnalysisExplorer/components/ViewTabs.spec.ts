import { beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import ViewTabs from "@/manuspectrum/pages/AnalysisExplorer/components/ViewTabs.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { ExplorerView } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const available = vi.hoisted(() => ({ views: ["corpus"] as string[] }));

vi.mock("@/manuspectrum/pages/AnalysisExplorer/views/registry.ts", () => ({
    availableViews: () => available.views,
    isViewAvailable: (view: string) => available.views.includes(view),
    EXPLORER_VIEWS: [],
}));

beforeEach(() => setActivePinia(createPinia()));

describe("ViewTabs", () => {
    it("renders nothing while Corpus is the only view", () => {
        available.views = ["corpus"];
        expect(mount(ViewTabs).find(".view-tabs").exists()).toBe(false);
    });

    it("marks the current view and switches on click", async () => {
        available.views = ["corpus", "compare"] satisfies ExplorerView[];
        const store = useExplorerStore();
        store.addToBasket("ch:00000000-0000-4000-8000-000000000001:-");
        const wrapper = mount(ViewTabs);
        const buttons = wrapper.findAll(".view-tabs button");
        expect(buttons.map((button) => button.text())).toEqual([
            "Corpus",
            "Compare (1)",
        ]);
        expect(buttons[0].attributes("aria-current")).toBe("page");
        await buttons[1].trigger("click");
        expect(store.view).toBe("compare");
        expect(buttons[1].attributes("aria-current")).toBe("page");
    });
});
