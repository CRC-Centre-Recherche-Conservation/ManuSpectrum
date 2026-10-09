import { enableAutoUnmount, mount } from "@vue/test-utils";
import PrimeVue from "primevue/config";
import Slider from "primevue/slider";
import { afterEach, describe, expect, it, vi } from "vitest";

import LayerControls from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/LayerControls.vue";

import type { FolioOverlay } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";

enableAutoUnmount(afterEach);

function overlay(patch: Partial<FolioOverlay> = {}): FolioOverlay {
    return {
        key: "a:0",
        url: "https://iiif.example/image/full/!2048,2048/0/default.jpg",
        fallbackUrls: [],
        bounds: [
            [-10, 0],
            [0, 10],
        ],
        opacity: 0.7,
        label: "Pb",
        analysis: "a",
        quarter: 0,
        registered: true,
        canTurn: true,
        ...patch,
    };
}

function mountBar(
    props: Partial<{
        overlay: FolioOverlay;
        adjusting: boolean;
        underCurtain: boolean;
        capturing: boolean;
        canCapture: boolean;
        turning: boolean;
    }> = {},
) {
    return mount(LayerControls, {
        props: {
            overlay: overlay(),
            adjusting: false,
            underCurtain: false,
            capturing: false,
            ...props,
        },
        global: { plugins: [PrimeVue] },
        attachTo: document.body,
    });
}

function nameOf(button: Element): string {
    const id = button.getAttribute("aria-labelledby") ?? "";
    return document.getElementById(id)?.textContent ?? "";
}

function buttonNamed(wrapper: ReturnType<typeof mountBar>, name: string) {
    const found = wrapper
        .findAll("button")
        .find((button) => nameOf(button.element) === name);
    if (!found) throw new Error(`No button named ${name}`);
    return found;
}

describe("LayerControls", () => {
    it("is a toolbar named after the layer", () => {
        const wrapper = mountBar();
        const bar = wrapper.get("[role=toolbar]");
        expect(bar.attributes("aria-label")).toBe("Layer on the page: Pb");
    });

    it("offers the seven controls, each named", () => {
        const wrapper = mountBar();
        expect(
            wrapper.findAll("button").map((button) => nameOf(button.element)),
        ).toEqual([
            "Adjust the layer",
            "Turn left",
            "Turn right",
            "Opacity",
            "Curtain: compare with the page",
            "Capture the folio under the layer",
            "Reset the position",
        ]);
    });

    it("emits the turn direction", async () => {
        const wrapper = mountBar();
        await buttonNamed(wrapper, "Turn right").trigger("click");
        await buttonNamed(wrapper, "Turn left").trigger("click");
        expect(wrapper.emitted("turn")).toEqual([[1], [-1]]);
    });

    it("disables the turns, with the reason, for a layer without image service", async () => {
        const wrapper = mountBar({ overlay: overlay({ canTurn: false }) });
        for (const name of ["Turn left", "Turn right"]) {
            const button = buttonNamed(wrapper, name);
            expect(button.attributes("aria-disabled")).toBe("true");
            const described = document.getElementById(
                button.attributes("aria-describedby") ?? "",
            );
            expect(described?.textContent).toContain(
                "This layer has no image service: it cannot turn",
            );
            await button.trigger("click");
        }
        expect(wrapper.emitted("turn")).toBeUndefined();
    });

    it("disables the turns while a turn is being checked", async () => {
        const wrapper = mountBar({ turning: true });
        for (const name of ["Turn left", "Turn right"]) {
            const button = buttonNamed(wrapper, name);
            expect(button.attributes("aria-disabled")).toBe("true");
            await button.trigger("click");
        }
        expect(wrapper.emitted("turn")).toBeUndefined();
    });

    it("draws the reset with a glyph of its own, not the turn-left one", () => {
        const wrapper = mountBar();
        const glyph = (name: string) =>
            buttonNamed(wrapper, name)
                .findAll("path")
                .map((path) => path.attributes("d"))
                .join("|");
        expect(glyph("Reset the position")).not.toBe(glyph("Turn left"));
    });

    it("disables the reset until the layer is registered", async () => {
        const wrapper = mountBar({ overlay: overlay({ registered: false }) });
        const reset = buttonNamed(wrapper, "Reset the position");
        expect(reset.attributes("aria-disabled")).toBe("true");
        await reset.trigger("click");
        expect(wrapper.emitted("reset")).toBeUndefined();
        await wrapper.setProps({ overlay: overlay() });
        await reset.trigger("click");
        expect(wrapper.emitted("reset")).toEqual([[]]);
    });

    it("shows the adjust and curtain toggles as pressed and emits their next state", async () => {
        const wrapper = mountBar({ adjusting: true, underCurtain: true });
        const adjust = buttonNamed(wrapper, "Adjust the layer");
        const curtain = buttonNamed(wrapper, "Curtain: compare with the page");
        expect(adjust.attributes("aria-pressed")).toBe("true");
        expect(curtain.attributes("aria-pressed")).toBe("true");
        await adjust.trigger("click");
        await curtain.trigger("click");
        expect(wrapper.emitted("adjust")).toEqual([[false]]);
        expect(wrapper.emitted("curtain")).toEqual([[false]]);
        await wrapper.setProps({ adjusting: false, underCurtain: false });
        expect(adjust.attributes("aria-pressed")).toBe("false");
        await curtain.trigger("click");
        expect(wrapper.emitted("curtain")?.at(-1)).toEqual([true]);
    });

    it("emits capture", async () => {
        const wrapper = mountBar();
        await buttonNamed(wrapper, "Capture the folio under the layer").trigger(
            "click",
        );
        expect(wrapper.emitted("capture")).toEqual([[]]);
    });

    it("opens the opacity slider on its button and emits a fraction", async () => {
        const wrapper = mountBar();
        expect(wrapper.findComponent(Slider).exists()).toBe(false);
        const opacity = buttonNamed(wrapper, "Opacity");
        expect(opacity.attributes("aria-expanded")).toBe("false");
        await opacity.trigger("click");
        expect(opacity.attributes("aria-expanded")).toBe("true");
        const slider = wrapper.getComponent(Slider);
        expect(slider.props("modelValue")).toBe(70);
        expect(wrapper.get("[role=slider]").attributes("aria-label")).toBe(
            "Opacity",
        );
        expect(slider.props("step")).toBe(5);
        slider.vm.$emit("update:modelValue", 40);
        expect(wrapper.emitted("opacity")).toEqual([[0.4]]);
    });

    it("closes the opacity slider on Escape and gives the focus back", async () => {
        const wrapper = mountBar();
        const opacity = buttonNamed(wrapper, "Opacity");
        await opacity.trigger("click");
        await wrapper
            .get(".opacity-popover")
            .trigger("keydown", { key: "Escape" });
        expect(wrapper.findComponent(Slider).exists()).toBe(false);
        expect(document.activeElement).toBe(opacity.element);
    });

    it("closes the slider on Escape from the sun button without letting the key reach the page", async () => {
        const seen = vi.fn();
        document.addEventListener("keydown", seen);
        const wrapper = mountBar();
        const opacity = buttonNamed(wrapper, "Opacity");
        expect(opacity.attributes("data-popover")).toBe("opacity");
        await opacity.trigger("click");
        (opacity.element as HTMLElement).focus();
        await opacity.trigger("keydown", { key: "Escape" });
        document.removeEventListener("keydown", seen);
        expect(wrapper.findComponent(Slider).exists()).toBe(false);
        expect(seen).not.toHaveBeenCalled();
        expect(document.activeElement).toBe(opacity.element);
    });

    it("disables the camera, with the reason, when the folio has no image service", () => {
        const wrapper = mountBar({ canCapture: false });
        const camera = buttonNamed(
            wrapper,
            "Capture the folio under the layer",
        );
        expect(camera.attributes("aria-disabled")).toBe("true");
        expect(
            document.getElementById(camera.attributes("aria-describedby") ?? "")
                ?.textContent,
        ).toBe("This folio has no image service: it cannot be captured.");
    });

    it("lets Escape through when the slider is closed", async () => {
        const seen = vi.fn();
        document.addEventListener("keydown", seen);
        const wrapper = mountBar();
        await buttonNamed(wrapper, "Opacity").trigger("keydown", {
            key: "Escape",
        });
        document.removeEventListener("keydown", seen);
        expect(seen).toHaveBeenCalledTimes(1);
    });

    it("moves the focus between the buttons with the arrow keys, one tab stop", async () => {
        const wrapper = mountBar();
        const buttons = wrapper.findAll("button");
        expect(buttons.map((button) => button.attributes("tabindex"))).toEqual([
            "0",
            "-1",
            "-1",
            "-1",
            "-1",
            "-1",
            "-1",
        ]);
        (buttons[0].element as HTMLElement).focus();
        await buttons[0].trigger("keydown", { key: "ArrowRight" });
        expect(document.activeElement).toBe(buttons[1].element);
        expect(buttons[1].attributes("tabindex")).toBe("0");
        expect(buttons[0].attributes("tabindex")).toBe("-1");
        await buttons[1].trigger("keydown", { key: "End" });
        expect(document.activeElement).toBe(buttons[6].element);
        await buttons[6].trigger("keydown", { key: "ArrowLeft" });
        expect(document.activeElement).toBe(buttons[5].element);
        await buttons[5].trigger("keydown", { key: "Home" });
        expect(document.activeElement).toBe(buttons[0].element);
    });
});
