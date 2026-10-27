import { enableAutoUnmount, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";

import { ICONS } from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";

enableAutoUnmount(afterEach);

function mountButton(props: Record<string, unknown> = {}) {
    return mount(IconButton, {
        props: { icon: "download", label: "Download CSV", ...props },
        attrs: { "data-action": "csv" },
        attachTo: document.body,
    });
}

function nameOf(button: Element): string | undefined {
    const id = button.getAttribute("aria-labelledby") ?? "";
    return document.getElementById(id)?.textContent ?? undefined;
}

describe("IconButton", () => {
    afterEach(() => {
        vi.useRealTimers();
    });

    it("draws its primeicons icon, hidden from assistive technologies", () => {
        const wrapper = mountButton();
        const svg = wrapper.find("button svg");
        expect(svg.attributes("aria-hidden")).toBe("true");
        expect(svg.attributes("focusable")).toBe("false");
        expect(svg.findAll("path").map((path) => path.attributes("d"))).toEqual(
            [...ICONS.download],
        );
    });

    it("draws the check icon", () => {
        const wrapper = mountButton({ icon: "check" });
        expect(
            wrapper
                .findAll("button svg path")
                .map((path) => path.attributes("d")),
        ).toEqual([...ICONS.check]);
    });

    it("is named by its tooltip, and read once", () => {
        const wrapper = mountButton();
        const button = wrapper.find("button").element;
        expect(nameOf(button)).toBe("Download CSV");
        expect(button.getAttribute("aria-label")).toBeNull();
        expect(button.getAttribute("aria-describedby")).toBeNull();
        expect(button.textContent?.trim()).toBe("");
    });

    it("is described by its description, which its tooltip shows too", async () => {
        vi.useFakeTimers();
        const wrapper = mountButton({ description: "Two columns per curve." });
        const button = wrapper.find("button").element;
        const described = document.getElementById(
            button.getAttribute("aria-describedby") ?? "",
        );
        expect(described?.textContent).toBe("Two columns per curve.");
        button.focus();
        vi.advanceTimersByTime(500);
        await wrapper.vm.$nextTick();
        const tip = document.querySelector('[role="tooltip"]:not([hidden])');
        expect(tip?.textContent).toContain("Download CSV");
        expect(tip?.textContent).toContain("Two columns per curve.");
    });

    it("passes its attributes to the button and emits its clicks", async () => {
        const wrapper = mountButton();
        const button = wrapper.find("button");
        expect(button.attributes("data-action")).toBe("csv");
        expect(button.attributes("type")).toBe("button");
        await button.trigger("click");
        expect(wrapper.emitted("click")).toHaveLength(1);
    });

    it("is a toggle only when told whether it is pressed", async () => {
        const plain = mountButton();
        expect(plain.find("button").attributes("aria-pressed")).toBeUndefined();
        const toggle = mountButton({ pressed: false });
        expect(toggle.find("button").attributes("aria-pressed")).toBe("false");
        await toggle.setProps({ pressed: true });
        expect(toggle.find("button").attributes("aria-pressed")).toBe("true");
    });

    it("stays focusable when disabled, and emits nothing", async () => {
        const wrapper = mountButton({ disabled: true });
        const button = wrapper.find("button");
        expect(button.attributes("aria-disabled")).toBe("true");
        expect(button.attributes("disabled")).toBeUndefined();
        button.element.focus();
        expect(document.activeElement).toBe(button.element);
        await button.trigger("click");
        expect(wrapper.emitted("click")).toBeUndefined();
    });

    it("gives its button to its parent, for the focus", () => {
        const wrapper = mountButton();
        const exposed = wrapper.vm as unknown as {
            element: HTMLButtonElement | null;
        };
        expect(exposed.element).toBe(wrapper.find("button").element);
    });
});
