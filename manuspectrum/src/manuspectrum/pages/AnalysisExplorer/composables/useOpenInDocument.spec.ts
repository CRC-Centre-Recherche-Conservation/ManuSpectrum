import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { defineComponent, h, ref } from "vue";

import {
    isPlainClick,
    useOpenInDocument,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useOpenInDocument.ts";
import { SCREEN_FOCUS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { uuid } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const TARGET = {
    document: uuid(1),
    canvas: null,
    focus: { kind: "analysis", id: uuid(101) },
} as const;

function click(init: MouseEventInit = {}): MouseEvent {
    return new MouseEvent("click", { cancelable: true, ...init });
}

beforeEach(() => setActivePinia(createPinia()));

describe("isPlainClick", () => {
    it("accepts the primary button alone", () => {
        expect(isPlainClick(click())).toBe(true);
    });

    it.each([
        { button: 1 },
        { ctrlKey: true },
        { metaKey: true },
        { shiftKey: true },
        { altKey: true },
    ])("refuses %j", (init) => {
        expect(isPlainClick(click(init))).toBe(false);
    });

    it("refuses a click another handler already took", () => {
        const event = click();
        event.preventDefault();
        expect(isPlainClick(event)).toBe(false);
    });
});

describe("useOpenInDocument", () => {
    it("navigates and prevents the default on a plain click", () => {
        const store = useExplorerStore();
        const event = click();
        expect(useOpenInDocument().open(TARGET, event)).toBe(true);
        expect(event.defaultPrevented).toBe(true);
        expect(store.document).toEqual({ id: TARGET.document, canvas: null });
        expect(store.focus).toEqual(TARGET.focus);
    });

    it("leaves a click with a modifier alone", () => {
        const store = useExplorerStore();
        const event = click({ ctrlKey: true });
        expect(useOpenInDocument().open(TARGET, event)).toBe(false);
        expect(event.defaultPrevented).toBe(false);
        expect(store.document).toBeNull();
    });

    it("writes the address of the document, its page and its card", () => {
        const href = useOpenInDocument().hrefOf({
            ...TARGET,
            canvas: "https://iiif.example/c2",
        });
        const query = new URLSearchParams(href.slice(1));
        expect(query.get("doc")).toBe(TARGET.document);
        expect(query.get("canvas")).toBe("https://iiif.example/c2");
        expect(query.get("focus")).toBe(`analysis:${uuid(101)}`);
    });

    it("asks for the heading of the screen shown to take the focus, on a plain click only", () => {
        const pending = ref(false);
        let opener!: ReturnType<typeof useOpenInDocument>;
        mount(
            defineComponent({
                setup() {
                    opener = useOpenInDocument();
                    return () => h("div");
                },
            }),
            { global: { provide: { [SCREEN_FOCUS_KEY as symbol]: pending } } },
        );
        opener.open(TARGET, click({ ctrlKey: true }));
        expect(pending.value).toBe(false);
        opener.open(TARGET, click());
        expect(pending.value).toBe(true);
    });
});
