import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import BulkStatusLine from "@/manuspectrum/pages/AnalysisExplorer/components/BulkStatusLine.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { BulkStatus } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const ADDED: BulkStatus = {
    kind: "added",
    keys: ["an:1", "an:2"],
    slots: ["A3", "A4"],
    total: 4,
};

beforeEach(() => setActivePinia(createPinia()));

describe("BulkStatusLine", () => {
    it("opens Compare when asked to compare", async () => {
        const wrapper = mount(BulkStatusLine, { props: { status: ADDED } });
        await wrapper.get('[data-action="compare"]').trigger("click");
        expect(useExplorerStore().view).toBe("compare");
    });

    it("renders nothing without a status", () => {
        const wrapper = mount(BulkStatusLine, { props: { status: null } });
        expect(wrapper.find('[role="status"]').exists()).toBe(false);
    });

    it("says what was added and under which slots, without the total", () => {
        const wrapper = mount(BulkStatusLine, { props: { status: ADDED } });
        const text = wrapper.get(".message").text();
        expect(text).toBe("2 analyses added (A3 to A4).");
        expect(text).not.toContain("30");
    });

    it("uses the singular and the kind of the keys", () => {
        const line = (keys: string[], slots: string[]) =>
            mount(BulkStatusLine, {
                props: { status: { kind: "added", keys, slots, total: 3 } },
            })
                .get(".message")
                .text();
        expect(line(["an:1"], ["A3"])).toBe("1 analysis added (A3).");
        expect(line(["ch:1:-", "ch:2:-"], ["A1", "A2"])).toBe(
            "2 identified materials added (A1 to A2).",
        );
        expect(line(["af:1:2"], ["A1"])).toBe("1 item added (A1).");
    });

    it("adds that the Selection is full when the change filled it", () => {
        const wrapper = mount(BulkStatusLine, {
            props: { status: { ...ADDED, total: 30 } },
        });
        expect(wrapper.get(".message").text()).toBe(
            "2 analyses added (A3 to A4). The Selection is full.",
        );
        const below = mount(BulkStatusLine, {
            props: { status: { ...ADDED, total: 29 } },
        });
        expect(below.get(".message").text()).not.toContain("full");
    });

    it("says what was removed", () => {
        const wrapper = mount(BulkStatusLine, {
            props: {
                status: {
                    kind: "removed",
                    keys: ["an:1"],
                    slots: ["A1"],
                    total: 0,
                },
            },
        });
        expect(wrapper.get('[role="status"]').text()).toContain(
            "1 analysis removed from the Selection.",
        );
    });

    it("emits undo, compare and dismiss from its buttons", async () => {
        const wrapper = mount(BulkStatusLine, { props: { status: ADDED } });
        await wrapper.get('[data-action="undo"]').trigger("click");
        await wrapper.get('[data-action="compare"]').trigger("click");
        await wrapper.get('[data-action="dismiss"]').trigger("click");
        expect(wrapper.emitted("undo")).toHaveLength(1);
        expect(wrapper.emitted("compare")).toHaveLength(1);
        expect(wrapper.emitted("dismiss")).toHaveLength(1);
    });

    it("orders Undo before Compare and does not dismiss itself", async () => {
        const wrapper = mount(BulkStatusLine, { props: { status: ADDED } });
        const actions = wrapper
            .findAll("button")
            .map((button) => button.attributes("data-action"));
        expect(actions).toEqual(["undo", "compare", "dismiss"]);
        await new Promise((resolve) => setTimeout(resolve, 50));
        expect(wrapper.find('[role="status"]').exists()).toBe(true);
    });

    it("says the Selection was emptied and offers no Compare", () => {
        const wrapper = mount(BulkStatusLine, {
            props: {
                status: {
                    kind: "emptied",
                    keys: ["an:1", "an:2", "an:3"],
                    slots: ["A1", "A2", "A3"],
                    total: 0,
                },
            },
        });
        expect(wrapper.get('[role="status"]').text()).toContain(
            "Selection emptied (3).",
        );
        expect(wrapper.find('[data-action="compare"]').exists()).toBe(false);
        expect(wrapper.find('[data-action="undo"]').exists()).toBe(true);
    });
});
