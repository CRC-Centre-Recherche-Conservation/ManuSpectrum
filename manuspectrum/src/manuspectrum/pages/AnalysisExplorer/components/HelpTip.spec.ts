import { enableAutoUnmount, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";

import HelpTip from "@/manuspectrum/pages/AnalysisExplorer/components/HelpTip.vue";

enableAutoUnmount(afterEach);

const HELP = "Paste this link into a IIIF viewer.";
const DELAY_MS = 500;

function mountTip() {
    return mount(HelpTip, {
        props: { text: HELP },
        slots: {
            default: ({ describedby }: { describedby?: string }) =>
                h(
                    "button",
                    { type: "button", "aria-describedby": describedby },
                    "Copy",
                ),
        },
        attachTo: document.body,
    });
}

const LABEL = "Download CSV";
const DETAIL = "Two columns per curve.";

function mountLabel(detail?: string) {
    return mount(HelpTip, {
        props: { text: LABEL, mode: "label", detail },
        slots: {
            default: ({
                labelledby,
                describedby,
            }: {
                labelledby?: string;
                describedby?: string;
            }) =>
                h("button", {
                    type: "button",
                    "aria-labelledby": labelledby,
                    "aria-describedby": describedby,
                }),
        },
        attachTo: document.body,
    });
}

function shown(): Element | null {
    return document.body.querySelector('[role="tooltip"]:not([hidden])');
}

function pointer(type: string, pointerType = "mouse"): Event {
    return Object.assign(new Event(type, { bubbles: true }), { pointerType });
}

describe("HelpTip", () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.restoreAllMocks();
        vi.useRealTimers();
    });

    it("gives the trigger a hidden description, the one tooltip node", () => {
        const wrapper = mountTip();
        const button = wrapper.find("button");
        const tips = document.body.querySelectorAll('[role="tooltip"]');

        expect(tips).toHaveLength(1);
        expect(tips[0].id).toBe(button.attributes("aria-describedby"));
        expect(tips[0].hasAttribute("hidden")).toBe(true);
        expect(tips[0].textContent).toBe(HELP);
    });

    it("shows on hover after the delay, not a millisecond before", async () => {
        const wrapper = mountTip();
        wrapper.element.dispatchEvent(pointer("pointerenter"));

        vi.advanceTimersByTime(DELAY_MS - 1);
        await wrapper.vm.$nextTick();
        expect(shown()).toBeNull();
        vi.advanceTimersByTime(1);
        await wrapper.vm.$nextTick();
        expect(shown()?.textContent).toBe(HELP);
    });

    it("ignores a touch contact", async () => {
        const wrapper = mountTip();
        wrapper.element.dispatchEvent(pointer("pointerenter", "touch"));
        vi.advanceTimersByTime(DELAY_MS);
        await wrapper.vm.$nextTick();
        expect(shown()).toBeNull();
    });

    it("shows on keyboard focus after the delay", async () => {
        const wrapper = mountTip();
        wrapper.find("button").element.focus();

        vi.advanceTimersByTime(DELAY_MS - 1);
        await wrapper.vm.$nextTick();
        expect(shown()).toBeNull();
        vi.advanceTimersByTime(1);
        await wrapper.vm.$nextTick();
        expect(shown()?.textContent).toBe(HELP);
    });

    it("stays hidden on a focus that is not focus-visible", async () => {
        const wrapper = mountTip();
        const button = wrapper.find("button");
        const matches = Element.prototype.matches;
        vi.spyOn(button.element, "matches").mockImplementation(function (
            this: Element,
            selector: string,
        ) {
            return selector === ":focus-visible"
                ? false
                : matches.call(this, selector);
        });

        button.element.focus();
        vi.advanceTimersByTime(DELAY_MS);
        await wrapper.vm.$nextTick();
        expect(shown()).toBeNull();
    });

    it("shows nothing after a click or a tap", async () => {
        const wrapper = mountTip();
        const button = wrapper.find("button");

        wrapper.element.dispatchEvent(pointer("pointerenter"));
        button.element.dispatchEvent(pointer("pointerdown"));
        button.element.focus();
        await button.trigger("click");
        vi.advanceTimersByTime(DELAY_MS * 4);
        await wrapper.vm.$nextTick();
        expect(shown()).toBeNull();
    });

    it("shows nothing while a press holds the focus it gave", async () => {
        const wrapper = mountTip();
        const button = wrapper.find("button");

        button.element.dispatchEvent(pointer("pointerdown"));
        button.element.focus();
        vi.advanceTimersByTime(DELAY_MS * 4);
        await wrapper.vm.$nextTick();
        expect(shown()).toBeNull();
    });

    it("hides on a click while shown", async () => {
        const wrapper = mountTip();
        const button = wrapper.find("button");
        button.element.focus();
        vi.advanceTimersByTime(DELAY_MS);
        await wrapper.vm.$nextTick();
        expect(shown()).not.toBeNull();

        await button.trigger("click");
        expect(shown()).toBeNull();
    });

    it("stays while the pointer moves onto the tooltip, hides when it leaves", async () => {
        const wrapper = mountTip();
        wrapper.element.dispatchEvent(pointer("pointerenter"));
        vi.advanceTimersByTime(DELAY_MS);
        await wrapper.vm.$nextTick();

        const tip = shown() as Element;
        expect(wrapper.element.contains(tip)).toBe(true);
        wrapper.find("button").element.dispatchEvent(pointer("pointerleave"));
        tip.dispatchEvent(pointer("pointerenter"));
        vi.advanceTimersByTime(DELAY_MS);
        await wrapper.vm.$nextTick();
        expect(shown()).toBe(tip);

        wrapper.element.dispatchEvent(pointer("pointerleave"));
        await wrapper.vm.$nextTick();
        expect(shown()).toBeNull();
    });

    it("hides on blur", async () => {
        const wrapper = mountTip();
        const button = wrapper.find("button");
        button.element.focus();
        vi.advanceTimersByTime(DELAY_MS);
        await wrapper.vm.$nextTick();
        expect(shown()).not.toBeNull();

        button.element.blur();
        await wrapper.vm.$nextTick();
        expect(shown()).toBeNull();
    });

    it("hides on Escape pressed anywhere, and listens only while shown", async () => {
        const wrapper = mountTip();
        const listen = vi.spyOn(document, "addEventListener");
        const unlisten = vi.spyOn(document, "removeEventListener");
        expect(listen).not.toHaveBeenCalledWith(
            "keydown",
            expect.any(Function),
        );

        wrapper.element.dispatchEvent(pointer("pointerenter"));
        vi.advanceTimersByTime(DELAY_MS);
        await wrapper.vm.$nextTick();
        expect(listen).toHaveBeenCalledWith("keydown", expect.any(Function));

        document.body.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        );
        await wrapper.vm.$nextTick();
        expect(shown()).toBeNull();
        expect(unlisten).toHaveBeenCalledWith("keydown", expect.any(Function));
    });

    it("marks the Escape that hides it as handled, and leaves the others alone", async () => {
        const wrapper = mountTip();
        wrapper.element.dispatchEvent(pointer("pointerenter"));
        await wrapper.vm.$nextTick();
        const pending = new KeyboardEvent("keydown", {
            key: "Escape",
            bubbles: true,
            cancelable: true,
        });
        document.body.dispatchEvent(pending);
        expect(pending.defaultPrevented).toBe(false);

        wrapper.element.dispatchEvent(pointer("pointerleave"));
        wrapper.element.dispatchEvent(pointer("pointerenter"));
        vi.advanceTimersByTime(DELAY_MS);
        await wrapper.vm.$nextTick();
        const dismissing = new KeyboardEvent("keydown", {
            key: "Escape",
            bubbles: true,
            cancelable: true,
        });
        document.body.dispatchEvent(dismissing);
        expect(dismissing.defaultPrevented).toBe(true);
        await wrapper.vm.$nextTick();
        expect(shown()).toBeNull();
    });

    it("keeps showing on another key", async () => {
        const wrapper = mountTip();
        wrapper.element.dispatchEvent(pointer("pointerenter"));
        vi.advanceTimersByTime(DELAY_MS);
        await wrapper.vm.$nextTick();

        document.body.dispatchEvent(
            new KeyboardEvent("keydown", { key: "a", bubbles: true }),
        );
        await wrapper.vm.$nextTick();
        expect(shown()).not.toBeNull();
    });

    it("names its control in the label role, without describing it with the same text", () => {
        const wrapper = mountLabel();
        const button = wrapper.find("button");
        const name = document.getElementById(
            button.attributes("aria-labelledby") ?? "",
        );

        expect(name?.textContent).toBe(LABEL);
        expect(name?.closest('[role="tooltip"]')?.hasAttribute("hidden")).toBe(
            true,
        );
        expect(button.attributes("aria-describedby")).toBeUndefined();
    });

    it("describes its control by the detail alone in the label role, and shows both", async () => {
        const wrapper = mountLabel(DETAIL);
        const button = wrapper.find("button");
        const name = document.getElementById(
            button.attributes("aria-labelledby") ?? "",
        );
        const description = document.getElementById(
            button.attributes("aria-describedby") ?? "",
        );

        expect(name?.textContent).toBe(LABEL);
        expect(description?.textContent).toBe(DETAIL);
        button.element.focus();
        vi.advanceTimersByTime(DELAY_MS);
        await wrapper.vm.$nextTick();
        expect(shown()?.textContent).toContain(LABEL);
        expect(shown()?.textContent).toContain(DETAIL);
    });

    it("gives no label to its control in the description role", () => {
        const wrapper = mountTip();
        expect(wrapper.find("button").attributes("aria-labelledby")).toBe(
            undefined,
        );
    });

    it("cancels a pending show and its listener when unmounted", async () => {
        const wrapper = mountTip();
        const unlisten = vi.spyOn(document, "removeEventListener");
        wrapper.element.dispatchEvent(pointer("pointerenter"));
        vi.advanceTimersByTime(DELAY_MS);
        await wrapper.vm.$nextTick();

        wrapper.unmount();
        expect(unlisten).toHaveBeenCalledWith("keydown", expect.any(Function));
        expect(vi.getTimerCount()).toBe(0);
    });
});
