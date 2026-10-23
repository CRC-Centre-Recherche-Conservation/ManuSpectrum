import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { defineComponent, h, nextTick, ref } from "vue";

import {
    provideWindowActions,
    useWindowActions,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useWindowActions.ts";

import type { Component, Ref } from "vue";

import type { WindowAction } from "@/manuspectrum/pages/AnalysisExplorer/composables/useWindowActions.ts";

/** A window body declaring one action; a plain options object, so that the spec defines one component with `defineComponent`. */
function body(label: Ref<string>): Component {
    return {
        setup() {
            useWindowActions(() => [
                {
                    id: "csv",
                    icon: "download",
                    label: label.value,
                    run: () => {},
                },
            ]);
            return () => h("p");
        },
    };
}

describe("useWindowActions", () => {
    it("shows what a body declares in its host, follows it, and takes it away with the body", async () => {
        const label = ref("Download CSV");
        const shown = ref(true);
        let actions: { value: WindowAction[] } = { value: [] };
        const Body = body(label);
        const Host = defineComponent({
            setup() {
                actions = provideWindowActions();
                return () => (shown.value ? h(Body) : null);
            },
        });
        mount(Host);
        expect(actions.value.map((action) => action.label)).toEqual([
            "Download CSV",
        ]);
        label.value = "CSV";
        expect(actions.value.map((action) => action.label)).toEqual(["CSV"]);
        shown.value = false;
        await nextTick();
        expect(actions.value).toEqual([]);
    });

    it("declares nothing, and fails nothing, outside a host", () => {
        const wrapper = mount(body(ref("Download CSV")));
        expect(wrapper.find("p").exists()).toBe(true);
    });
});
