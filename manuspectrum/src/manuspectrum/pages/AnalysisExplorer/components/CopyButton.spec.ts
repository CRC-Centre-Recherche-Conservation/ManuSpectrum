import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import CopyButton from "@/manuspectrum/pages/AnalysisExplorer/components/CopyButton.vue";
import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";

import { ICONS } from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";

import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

class FakeClipboardItem {
    readonly items: Record<string, string>;

    constructor(items: Record<string, string>) {
        this.items = items;
    }
}

/** Gives the page's navigator a property for this test only. */
function lend(name: "clipboard" | "permissions", value: unknown): void {
    Object.defineProperty(navigator, name, { value, configurable: true });
}

afterEach(() => {
    for (const name of ["clipboard", "permissions"]) {
        Reflect.deleteProperty(navigator, name);
    }
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    document.body.innerHTML = "";
});

function mountButton(text: string, announce = vi.fn(), iconOnly = false) {
    const wrapper = mount(CopyButton, {
        attachTo: document.body,
        props: { text, label: "Copy BibTeX", iconOnly },
        global: { provide: { [ANNOUNCE_KEY as symbol]: announce } },
    });
    return { wrapper, announce };
}

describe("CopyButton", () => {
    it("copies its text and announces it", async () => {
        const write = vi.fn(async () => undefined);
        lend("clipboard", { write });
        lend("permissions", {
            query: async () =>
                Object.assign(new EventTarget(), { state: "granted" }),
        });
        vi.stubGlobal("ClipboardItem", FakeClipboardItem);
        const { wrapper, announce } = mountButton("@dataset{x}");
        await flushPromises();

        await wrapper.find("button").trigger("click");
        await flushPromises();

        expect(write).toHaveBeenCalledTimes(1);
        const [[[item]]] = write.mock.calls as unknown as [
            [[FakeClipboardItem]],
        ];
        expect(item.items["text/plain"]).toBe("@dataset{x}");
        expect(announce).toHaveBeenCalledWith("Copied");
        expect(wrapper.find("button").text()).toContain("Copied");
        wrapper.unmount();
    });

    it("falls back when the clipboard API is missing", async () => {
        expect("clipboard" in navigator).toBe(false);
        let copied = "";
        const execCommand = vi.fn((command: string) => {
            copied = document.querySelector("textarea")?.value ?? "";
            return command === "copy";
        });
        document.execCommand = execCommand;
        const { wrapper, announce } = mountButton("TY  - DATA");

        await wrapper.find("button").trigger("click");
        await flushPromises();

        expect(execCommand).toHaveBeenCalledWith("copy");
        expect(copied).toBe("TY  - DATA");
        expect(announce).toHaveBeenCalledWith("Copied");
        wrapper.unmount();
    });

    it("is disabled without text", async () => {
        const { wrapper, announce } = mountButton("");
        const button = wrapper.find("button");

        expect(button.attributes("disabled")).toBeDefined();
        await button.trigger("click");
        expect(announce).not.toHaveBeenCalled();
        wrapper.unmount();
    });

    it("is named by its label", () => {
        const { wrapper } = mountButton("x");
        expect(wrapper.find("button").text()).toBe("Copy BibTeX");
        wrapper.unmount();
    });

    function drawn(wrapper: ReturnType<typeof mountButton>["wrapper"]) {
        return wrapper
            .findAll("button svg path")
            .map((path) => path.attributes("d"));
    }

    it("as an icon, is an IconButton named by its label, with no title", () => {
        const { wrapper } = mountButton("@dataset{x}", vi.fn(), true);
        const button = wrapper.find("button");
        const name = wrapper.find(
            `[id="${button.attributes("aria-labelledby")}"]`,
        );

        expect(wrapper.findComponent(IconButton).exists()).toBe(true);
        expect(name.text()).toBe("Copy BibTeX");
        expect(button.attributes("title")).toBeUndefined();
        expect(button.attributes("aria-label")).toBeUndefined();
        expect(button.text()).toBe("");
        expect(drawn(wrapper)).toEqual([...ICONS.clone]);
        wrapper.unmount();
    });

    it("as an icon, shows a check once copied, then the copy icon again", async () => {
        vi.useFakeTimers();
        document.execCommand = vi.fn(() => true);
        const { wrapper } = mountButton("@dataset{x}", vi.fn(), true);

        await wrapper.find("button").trigger("click");
        await flushPromises();
        expect(drawn(wrapper)).toEqual([...ICONS.check]);

        await vi.advanceTimersByTimeAsync(3000);
        expect(drawn(wrapper)).toEqual([...ICONS.clone]);
        vi.useRealTimers();
        wrapper.unmount();
    });

    it("as an icon without text, is aria-disabled and copies nothing", async () => {
        const { wrapper, announce } = mountButton("", vi.fn(), true);
        const button = wrapper.find("button");

        expect(button.attributes("aria-disabled")).toBe("true");
        expect(button.attributes("disabled")).toBeUndefined();
        await button.trigger("click");
        expect(announce).not.toHaveBeenCalled();
        expect(drawn(wrapper)).toEqual([...ICONS.clone]);
        wrapper.unmount();
    });
});
