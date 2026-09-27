import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, inject, nextTick } from "vue";
import { flushPromises, mount } from "@vue/test-utils";

import WindowGrid from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/WindowGrid.vue";

import {
    ANNOUNCE_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    lastGrid,
    resetFakeGrids,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/gridstack.ts";
import { LAYOUT_STORAGE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { CompareWindowSpec } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

vi.mock("gridstack", async () =>
    (
        await import(
            "@/manuspectrum/pages/AnalysisExplorer/testing/gridstack.ts"
        )
    ).gridstackModule(),
);

const XRF: CompareWindowSpec = { id: "auto:xy:xrf", title: "XRF", size: "M" };
const MICRO: CompareWindowSpec = {
    id: "auto:micro",
    title: "Micro-images",
    size: "S",
};
const MATERIALS: CompareWindowSpec = {
    id: "auto:characterizations",
    title: "Identified materials",
    size: "M",
};

const ResizeReader = defineComponent({
    setup() {
        const tick = inject(WINDOW_RESIZE_KEY)!;
        return () => h("output", { class: "tick" }, String(tick.value));
    },
});

let announce: ReturnType<typeof vi.fn>;
let wrapper: VueWrapper | null = null;

function mountGrid(
    windows: CompareWindowSpec[] = [XRF, MICRO],
    retained: string[] = [],
): VueWrapper {
    wrapper = mount(WindowGrid, {
        props: { windows, retained },
        attachTo: document.body,
        global: { provide: { [ANNOUNCE_KEY as symbol]: announce } },
        slots: {
            default: `<template #default="{ window }"><p class="content">{{ window.id }}</p></template>`,
        },
    });
    return wrapper;
}

function item(id: string): HTMLElement {
    return document.querySelector<HTMLElement>(
        `.grid-stack-item[data-window-id="${id}"]`,
    )!;
}

function control(id: string, action: string): HTMLButtonElement {
    return item(id).querySelector<HTMLButtonElement>(
        `[data-action="${action}"]`,
    )!;
}

function stored(): unknown {
    const raw = window.localStorage.getItem(LAYOUT_STORAGE_KEY);
    if (raw === null) return null;
    const parsed = JSON.parse(raw);
    return parsed.version === 2 ? parsed.boxes : parsed;
}

beforeEach(() => {
    resetFakeGrids();
    window.localStorage.clear();
    announce = vi.fn();
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

describe("WindowGrid", () => {
    it("renders each window with its title and content", () => {
        mountGrid();
        expect(item(XRF.id).querySelector("h3")?.textContent).toBe("XRF");
        expect(item(MICRO.id).querySelector(".content")?.textContent).toBe(
            "auto:micro",
        );
    });

    it("arranges windows automatically while no layout is saved, and saves none", () => {
        mountGrid();
        const grid = lastGrid();
        expect(grid.makeWidget).toHaveBeenCalledWith(item(XRF.id), {
            id: XRF.id,
            autoPosition: true,
            w: 6,
            h: 5,
        });
        expect(grid.makeWidget).toHaveBeenCalledWith(item(MICRO.id), {
            id: MICRO.id,
            autoPosition: true,
            w: 4,
            h: 4,
        });
        expect(stored()).toBeNull();
    });

    it("puts a window back where it was saved and forgets windows no longer shown", () => {
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({
                [XRF.id]: { x: 6, y: 0, w: 6, h: 5 },
                "tool:periodic:-": { x: 0, y: 0, w: 4, h: 4 },
            }),
        );
        mountGrid();
        expect(lastGrid().makeWidget).toHaveBeenCalledWith(item(XRF.id), {
            id: XRF.id,
            x: 6,
            y: 0,
            w: 6,
            h: 5,
        });
        expect(stored()).toEqual({ [XRF.id]: { x: 6, y: 0, w: 6, h: 5 } });
    });

    it("saves what gridstack reports after a drag, except in one column", () => {
        mountGrid();
        const grid = lastGrid();
        grid.trigger("change");
        expect(stored()).toEqual({
            [XRF.id]: { x: 0, y: 0, w: 6, h: 5 },
            [MICRO.id]: { x: 0, y: 5, w: 4, h: 4 },
        });
        window.localStorage.clear();
        grid.setColumns(1);
        grid.trigger("change");
        expect(stored()).toBeNull();
    });

    it("grows to one column under 768 px", () => {
        mountGrid();
        expect(lastGrid().options.columnOpts).toEqual({
            breakpoints: [{ w: 768, c: 1 }],
            breakpointForWindow: true,
            layout: "list",
        });
        expect(lastGrid().options.column).toBe(12);
    });

    it("rearranges: empties the saved layout and lays the windows out in their order", async () => {
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({ [MICRO.id]: { x: 0, y: 0, w: 4, h: 4 } }),
        );
        const view = mountGrid();
        const grid = lastGrid();
        await view.find("button.rearrange").trigger("click");
        expect(grid.update).toHaveBeenCalledWith(item(XRF.id), {
            x: 0,
            y: 0,
            w: 6,
            h: 5,
        });
        expect(grid.update).toHaveBeenCalledWith(item(MICRO.id), {
            x: 6,
            y: 0,
            w: 4,
            h: 4,
        });
        expect(stored()).toBeNull();
        expect(announce).toHaveBeenCalledWith("Windows rearranged.");
    });

    it("moves a window after the next one, says where it is and keeps the focus on it", async () => {
        mountGrid();
        const grid = lastGrid();
        const button = control(XRF.id, "move-after");
        button.focus();
        button.click();
        await nextTick();
        expect(grid.update).toHaveBeenCalledWith(item(MICRO.id), {
            x: 0,
            y: 0,
            w: 4,
            h: 4,
        });
        expect(grid.update).toHaveBeenCalledWith(item(XRF.id), {
            x: 4,
            y: 0,
            w: 6,
            h: 5,
        });
        expect(announce).toHaveBeenLastCalledWith("XRF: 2 of 2");
        expect(document.activeElement).toBe(control(XRF.id, "move-after"));
        expect(
            control(XRF.id, "move-after").getAttribute("aria-disabled"),
        ).toBe("true");
        expect(stored()).toEqual({
            [MICRO.id]: { x: 0, y: 0, w: 4, h: 4 },
            [XRF.id]: { x: 4, y: 0, w: 6, h: 5 },
        });
    });

    it("does not move the first window before", async () => {
        mountGrid();
        const button = control(XRF.id, "move-before");
        expect(button.getAttribute("aria-disabled")).toBe("true");
        button.click();
        await nextTick();
        expect(lastGrid().update).not.toHaveBeenCalled();
        expect(announce).not.toHaveBeenCalled();
    });

    it("sizes a window S, M or L and marks the size it has", async () => {
        mountGrid();
        const grid = lastGrid();
        expect(control(XRF.id, "size-M").getAttribute("aria-pressed")).toBe(
            "true",
        );
        control(XRF.id, "size-L").click();
        await nextTick();
        expect(grid.update).toHaveBeenCalledWith(item(XRF.id), {
            w: 12,
            h: 6,
        });
        expect(control(XRF.id, "size-L").getAttribute("aria-pressed")).toBe(
            "true",
        );
        expect(control(XRF.id, "size-M").getAttribute("aria-pressed")).toBe(
            "false",
        );
        expect(control(XRF.id, "size-L").getAttribute("aria-label")).toBe(
            "Size L",
        );
        expect(announce).toHaveBeenLastCalledWith("XRF: size L");
    });

    it("asks for a window to be closed, and gives it back to gridstack when it goes", async () => {
        const view = mountGrid();
        const element = item(XRF.id);
        control(XRF.id, "close").click();
        await nextTick();
        expect(view.emitted("close")).toEqual([[{ id: XRF.id }]]);
        await view.setProps({ windows: [MICRO] });
        await nextTick();
        expect(lastGrid().removeWidget).toHaveBeenCalledWith(
            element,
            false,
            true,
        );
        expect(document.activeElement).toBe(
            item(MICRO.id).querySelector(".compare-window"),
        );
    });

    it("keeps the places of hidden windows and forgets those of windows gone", async () => {
        const box = { x: 6, y: 0, w: 6, h: 5 };
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({
                [XRF.id]: { x: 0, y: 0, w: 6, h: 5 },
                [MICRO.id]: box,
                [MATERIALS.id]: box,
            }),
        );
        const view = mountGrid([XRF], [MICRO.id, MATERIALS.id]);
        expect(stored()).toEqual({
            [XRF.id]: { x: 0, y: 0, w: 6, h: 5 },
            [MICRO.id]: box,
            [MATERIALS.id]: box,
        });
        await view.setProps({ windows: [XRF], retained: [MICRO.id] });
        await view.setProps({ windows: [], retained: [MICRO.id] });
        await nextTick();
        expect(stored()).toEqual({ [MICRO.id]: box });
    });

    it("brings a window back to its place and says it is shown again", async () => {
        const box = { x: 6, y: 0, w: 6, h: 5 };
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({ [MICRO.id]: box }),
        );
        const view = mountGrid([XRF], [MICRO.id]);
        await view.setProps({ windows: [XRF, MICRO], retained: [] });
        expect(lastGrid().makeWidget).toHaveBeenLastCalledWith(item(MICRO.id), {
            id: MICRO.id,
            ...box,
        });
        expect(announce).toHaveBeenLastCalledWith(
            "Window back in its place: Micro-images",
        );
    });

    it("lets its parent bring hidden windows back before it lays every window out", async () => {
        const grid: VueWrapper = mount(WindowGrid, {
            props: {
                windows: [MICRO],
                retained: [XRF.id],
                onRearrange: () => grid.setProps({ windows: [XRF, MICRO] }),
            },
            attachTo: document.body,
            global: { provide: { [ANNOUNCE_KEY as symbol]: announce } },
        });
        wrapper = grid;
        await wrapper.find("button.rearrange").trigger("click");
        await flushPromises();
        expect(lastGrid().update).toHaveBeenCalledWith(item(XRF.id), {
            x: 0,
            y: 0,
            w: 6,
            h: 5,
        });
        expect(lastGrid().update).toHaveBeenCalledWith(item(MICRO.id), {
            x: 6,
            y: 0,
            w: 4,
            h: 4,
        });
        expect(announce).toHaveBeenCalledTimes(1);
        expect(announce).toHaveBeenLastCalledWith("Windows rearranged.");
        expect(stored()).toBeNull();
    });

    it("opens a folded window to its header only, and unfolds it on demand", async () => {
        const folded: CompareWindowSpec = { ...XRF, folded: true };
        const view = mountGrid([MICRO, folded]);
        const grid = lastGrid();
        expect(grid.makeWidget).toHaveBeenCalledWith(item(XRF.id), {
            id: XRF.id,
            autoPosition: true,
            w: 6,
            h: 2,
        });
        expect(item(XRF.id).querySelector(".content")).toBeNull();
        expect(control(XRF.id, "fold").getAttribute("aria-expanded")).toBe(
            "false",
        );
        expect(control(MICRO.id, "fold")).toBeNull();
        control(XRF.id, "fold").click();
        await nextTick();
        expect(grid.update).toHaveBeenLastCalledWith(item(XRF.id), { h: 5 });
        expect(item(XRF.id).querySelector(".content")?.textContent).toBe(
            XRF.id,
        );
        expect(announce).toHaveBeenLastCalledWith("XRF: unfolded");
        control(XRF.id, "fold").click();
        await nextTick();
        expect(grid.update).toHaveBeenLastCalledWith(item(XRF.id), { h: 2 });
        expect(announce).toHaveBeenLastCalledWith("XRF: folded");
        control(XRF.id, "size-L").click();
        await nextTick();
        expect(control(XRF.id, "fold").getAttribute("aria-expanded")).toBe(
            "true",
        );
        await view.find("button.rearrange").trigger("click");
        await flushPromises();
        expect(grid.update).toHaveBeenLastCalledWith(item(XRF.id), {
            x: 4,
            y: 0,
            w: 6,
            h: 5,
        });
    });

    it("keeps a window folded as it opened when its place among the windows changes", async () => {
        const view = mountGrid([MICRO, { ...XRF, folded: true }]);
        await view.setProps({ windows: [{ ...XRF, folded: false }] });
        expect(control(XRF.id, "fold").getAttribute("aria-expanded")).toBe(
            "false",
        );
    });

    it("puts a new window at the end without taking the focus, and says so", async () => {
        const view = mountGrid();
        const grid = lastGrid();
        const button = view.find<HTMLButtonElement>("button.rearrange");
        button.element.focus();
        await view.setProps({ windows: [XRF, MICRO, MATERIALS] });
        expect(grid.makeWidget).toHaveBeenLastCalledWith(item(MATERIALS.id), {
            id: MATERIALS.id,
            x: 0,
            y: 9,
            w: 6,
            h: 5,
        });
        expect(announce).toHaveBeenLastCalledWith(
            "New window at the end: Identified materials",
        );
        expect(document.activeElement).toBe(button.element);
    });

    it("tells the windows once when the grid has changed size", async () => {
        vi.useFakeTimers();
        const observers: ResizeObserverCallback[] = [];
        const disconnect = vi.fn();
        vi.stubGlobal(
            "ResizeObserver",
            class {
                constructor(callback: ResizeObserverCallback) {
                    observers.push(callback);
                }
                observe(): void {}
                disconnect(): void {
                    disconnect();
                }
            },
        );
        wrapper = mount(WindowGrid, {
            props: { windows: [XRF, MICRO] },
            attachTo: document.body,
            global: { provide: { [ANNOUNCE_KEY as symbol]: announce } },
            slots: { default: () => h(ResizeReader) },
        });
        expect(observers).toHaveLength(1);
        observers[0]([], {} as ResizeObserver);
        lastGrid().trigger("resizestop");
        observers[0]([], {} as ResizeObserver);
        await vi.advanceTimersByTimeAsync(300);
        expect(wrapper.findAll(".tick").map((tick) => tick.text())).toEqual([
            "1",
            "1",
        ]);
        wrapper.unmount();
        wrapper = null;
        expect(disconnect).toHaveBeenCalled();
        expect(lastGrid().destroy).toHaveBeenCalledWith(false);
    });
});
