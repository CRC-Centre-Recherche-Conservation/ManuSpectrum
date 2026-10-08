import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import SelectionCapacityNotice from "@/manuspectrum/pages/AnalysisExplorer/components/SelectionCapacityNotice.vue";

import { useSelectionToggle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionToggle.ts";
import {
    ANNOUNCE_KEY,
    SELECTION_DRAWER_KEY,
    SELECTION_HINTS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { analysisKey } from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { uuid } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

const open = vi.fn();
const hints = ref(new Map<string, SelectionHint>());

function keys(count: number, from = 1): string[] {
    return Array.from({ length: count }, (_, n) => analysisKey(uuid(from + n)));
}

function hold(count: number): void {
    useExplorerStore().addManyToBasket(keys(count, 100));
}

function mountNotice(zone: string[]) {
    return mount(SelectionCapacityNotice, {
        props: { keys: zone, id: "zone-notice" },
        global: {
            provide: {
                [ANNOUNCE_KEY as symbol]: vi.fn(),
                [SELECTION_HINTS_KEY as symbol]: hints,
                [SELECTION_DRAWER_KEY as symbol]: { open },
            },
        },
    });
}

function mountToggle(): ReturnType<typeof useSelectionToggle> {
    let toggle!: ReturnType<typeof useSelectionToggle>;
    mount(
        {
            setup() {
                toggle = useSelectionToggle();
                return () => null;
            },
        },
        {
            global: {
                provide: {
                    [ANNOUNCE_KEY as symbol]: vi.fn(),
                    [SELECTION_HINTS_KEY as symbol]: hints,
                },
            },
        },
    );
    return toggle;
}

beforeEach(() => {
    setActivePinia(createPinia());
    open.mockClear();
    mountToggle().dismiss();
});

describe("SelectionCapacityNotice", () => {
    it("shows nothing while the zone fits", () => {
        hold(25);
        expect(
            mountNotice(keys(5)).find(".selection-capacity-notice").exists(),
        ).toBe(false);
    });

    it("shows nothing when the whole zone is already held", () => {
        hold(30);
        const zone = keys(3, 100);
        expect(
            mountNotice(zone).find(".selection-capacity-notice").exists(),
        ).toBe(false);
    });

    it("says the Selection is full and what to do", () => {
        hold(30);
        const notice = mountNotice(keys(6));
        expect(notice.get(".title").text()).toBe("Selection full (30 / 30)");
        expect(notice.get(".text").text()).toBe("Remove items to add others.");
        expect(notice.attributes("id")).toBe("zone-notice");
        expect(notice.attributes("role")).toBeUndefined();
        expect(notice.find("[aria-live]").exists()).toBe(false);
    });

    it("says how many places are left when the zone does not fit", () => {
        hold(27);
        const notice = mountNotice(keys(4));
        expect(notice.get(".title").text()).toBe(
            "Only 3 places left in the Selection",
        );
        expect(notice.get(".text").text()).toBe(
            "This page has 4 analyses to add: tick them one by one or make room.",
        );
    });

    it("uses the singular for one place left", () => {
        hold(29);
        expect(mountNotice(keys(4)).get(".title").text()).toBe(
            "Only one place left in the Selection",
        );
    });

    it("hides while a grouped change is on screen", async () => {
        const notice = mountNotice(keys(4));
        expect(notice.find(".selection-capacity-notice").exists()).toBe(false);
        hold(27);
        await notice.vm.$nextTick();
        expect(notice.find(".selection-capacity-notice").exists()).toBe(true);
        const toggle = mountToggle();
        toggle.toggleAll(keys(2, 200));
        await notice.vm.$nextTick();
        expect(toggle.lastBulk.value).not.toBeNull();
        expect(notice.find(".selection-capacity-notice").exists()).toBe(false);
    });

    it("opens the Selection from its button", async () => {
        hold(30);
        const notice = mountNotice(keys(2));
        const button = notice.get("button");
        expect(button.text()).toBe("Open the Selection");
        await button.trigger("click");
        expect(open).toHaveBeenCalledTimes(1);
    });
});
