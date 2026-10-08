import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { defineComponent } from "vue";

import {
    reloadXrfSettings,
    useXrfSettings,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useXrfSettings.ts";
import {
    LAYOUT_STORAGE_KEY,
    writeXrfSettings,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";

let settings!: ReturnType<typeof useXrfSettings>["settings"];

function host() {
    return mount(
        defineComponent({
            setup() {
                ({ settings } = useXrfSettings());
                return () => null;
            },
        }),
    );
}

/** What another tab does: it writes the layout record, the browser tells this tab. */
function otherTabWrites(elements: string[], key = LAYOUT_STORAGE_KEY): void {
    writeXrfSettings({ detector: "sdd", anodes: {}, elements });
    window.dispatchEvent(new StorageEvent("storage", { key }));
}

beforeEach(() => {
    localStorage.clear();
    reloadXrfSettings();
});

afterEach(() => {
    localStorage.clear();
    reloadXrfSettings();
});

describe("useXrfSettings", () => {
    it("adopts the settings another tab wrote, and nothing else's storage event", () => {
        const view = host();
        otherTabWrites(["Fe"]);
        expect(settings.value.elements).toEqual(["Fe"]);
        otherTabWrites(["Fe", "Cu"], "ms-explorer-basket-v1");
        expect(settings.value.elements).toEqual(["Fe"]);
        view.unmount();
    });

    it("adopts a cleared storage and stops listening once its scope is gone", () => {
        const view = host();
        otherTabWrites(["Fe"]);
        localStorage.clear();
        window.dispatchEvent(new StorageEvent("storage", { key: null }));
        expect(settings.value.elements).toEqual([]);
        view.unmount();
        otherTabWrites(["Cu"]);
        expect(settings.value.elements).toEqual([]);
    });

    it("keeps adopting foreign writes while one window is left", () => {
        const first = host();
        const second = host();
        first.unmount();
        otherTabWrites(["Fe"]);
        expect(settings.value.elements).toEqual(["Fe"]);
        second.unmount();
    });
});
