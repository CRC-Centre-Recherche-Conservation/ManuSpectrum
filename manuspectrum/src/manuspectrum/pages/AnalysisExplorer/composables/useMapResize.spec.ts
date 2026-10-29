import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { defineComponent, h, useTemplateRef } from "vue";

import { useMapResize } from "@/manuspectrum/pages/AnalysisExplorer/composables/useMapResize.ts";

let observed: ResizeObserverCallback[] = [];
let disconnect: ReturnType<typeof vi.fn>;
let frames: FrameRequestCallback[] = [];

beforeEach(() => {
    observed = [];
    frames = [];
    disconnect = vi.fn();
    vi.stubGlobal(
        "ResizeObserver",
        class {
            constructor(callback: ResizeObserverCallback) {
                observed.push(callback);
            }
            observe = vi.fn();
            disconnect = disconnect;
        },
    );
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) =>
        frames.push(callback),
    );
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
});

afterEach(() => vi.unstubAllGlobals());

function mountWith(held: boolean): {
    invalidateSize: ReturnType<typeof vi.fn>;
    refit: ReturnType<typeof vi.fn>;
    unmount: () => void;
} {
    const invalidateSize = vi.fn();
    const refit = vi.fn();
    const view = mount(
        defineComponent({
            setup() {
                const host = useTemplateRef<HTMLElement>("host");
                useMapResize({
                    host,
                    map: () => ({ invalidateSize }) as never,
                    keepsFit: () => held,
                    refit,
                });
                return () => h("div", { ref: "host" });
            },
        }),
    );
    return { invalidateSize, refit, unmount: () => view.unmount() };
}

function fireResize(): void {
    observed.forEach((callback) =>
        callback([], {} as unknown as ResizeObserver),
    );
    frames.splice(0).forEach((frame) => frame(0));
}

describe("useMapResize", () => {
    it("reads the size again and fits the image again when the container changes size and the view is the fit", () => {
        const { invalidateSize, refit } = mountWith(true);
        fireResize();
        expect(invalidateSize).toHaveBeenCalledTimes(1);
        expect(refit).toHaveBeenCalledTimes(1);
    });

    it("leaves a view the reader moved where it is", () => {
        const { invalidateSize, refit } = mountWith(false);
        fireResize();
        expect(invalidateSize).toHaveBeenCalledTimes(1);
        expect(refit).not.toHaveBeenCalled();
    });

    it("answers once for several changes in one frame", () => {
        const { invalidateSize } = mountWith(true);
        observed.forEach((callback) =>
            callback([], {} as unknown as ResizeObserver),
        );
        observed.forEach((callback) =>
            callback([], {} as unknown as ResizeObserver),
        );
        frames.splice(0).forEach((frame) => frame(0));
        expect(invalidateSize).toHaveBeenCalledTimes(1);
    });

    it("stops observing when the component goes", () => {
        const { unmount } = mountWith(true);
        unmount();
        expect(disconnect).toHaveBeenCalled();
    });
});
