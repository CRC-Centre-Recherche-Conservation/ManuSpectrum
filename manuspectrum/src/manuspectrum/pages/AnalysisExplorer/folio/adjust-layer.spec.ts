import L from "leaflet";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { adjustLayer } from "@/manuspectrum/pages/AnalysisExplorer/folio/adjust-layer.ts";
import {
    boundsOfBox,
    boxOfBounds,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";

import { sizedContainer } from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";

import type { Box } from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";

const START: Box = { x: 3200, y: 3200, w: 6400, h: 3200 };
const LABEL = "Adjusting Pb: arrows move, plus and minus scale, Escape stops";

let map: L.Map;
let layer: L.ImageOverlay;
let image: HTMLImageElement;
let changes: Box[];
let done: Box[];
let exits: number;

beforeEach(() => {
    vi.useFakeTimers();
    map = L.map(sizedContainer(800, 600), {
        crs: L.CRS.Simple,
        zoomControl: false,
        attributionControl: false,
    });
    map.setView([-150, 150], 0, { animate: false });
    layer = L.imageOverlay("https://iiif.example/i.jpg", boundsOfBox(START), {
        className: "folio-overlay",
    }).addTo(map);
    image = layer.getElement() as HTMLImageElement;
    changes = [];
    done = [];
    exits = 0;
});

afterEach(() => {
    map.remove();
    document.body.replaceChildren();
    vi.useRealTimers();
});

function begin() {
    return adjustLayer(map, layer, START, {
        label: LABEL,
        onChange: (box) => changes.push(box),
        onDone: (box) => done.push(box),
        onExit: () => {
            exits += 1;
        },
    });
}

function pointer(
    target: Element,
    type: "pointerdown" | "pointermove" | "pointerup",
    x: number,
    y: number,
    init: MouseEventInit = {},
): void {
    target.dispatchEvent(
        new MouseEvent(type, {
            bubbles: true,
            cancelable: true,
            clientX: x,
            clientY: y,
            ...init,
        }),
    );
}

function key(
    type: "keydown" | "keyup",
    name: string,
    init: KeyboardEventInit = {},
): KeyboardEvent {
    const event = new KeyboardEvent(type, {
        key: name,
        bubbles: true,
        cancelable: true,
        ...init,
    });
    image.dispatchEvent(event);
    return event;
}

function corners(): [[number, number], [number, number]] {
    const bounds = layer.getBounds();
    return [
        [bounds.getSouth(), bounds.getWest()],
        [bounds.getNorth(), bounds.getEast()],
    ];
}

function handle(corner: string): HTMLElement {
    return layer
        .getPane()!
        .querySelector<HTMLElement>(`.adjust-handle[data-corner=${corner}]`)!;
}

describe("adjustLayer", () => {
    it("makes the image focusable and named, and puts four handles in its pane", () => {
        begin();
        expect(image.getAttribute("tabindex")).toBe("0");
        expect(image.getAttribute("aria-label")).toBe(LABEL);
        expect(image.classList).toContain("is-adjusting");
        expect(
            [...layer.getPane()!.querySelectorAll(".adjust-handle")].map(
                (element) => element.getAttribute("data-corner"),
            ),
        ).toEqual(["nw", "ne", "se", "sw"]);
    });

    it("places each handle on its corner of the box and follows the map", () => {
        begin();
        const point = (x: number, y: number) =>
            map.latLngToLayerPoint([-y / 32, x / 32]);
        const at = (corner: string) => {
            const position = L.DomUtil.getPosition(handle(corner));
            return [position.x, position.y];
        };
        const half = (handle("se").offsetWidth || 0) / 2;
        const se = point(START.x + START.w, START.y + START.h);
        expect(at("se")).toEqual([se.x - half, se.y - half]);
        map.setView([-100, 100], 1, { animate: false });
        const moved = point(START.x + START.w, START.y + START.h);
        expect(at("se")).toEqual([moved.x - half, moved.y - half]);
    });

    it("moves the box by a drag of the image, in container pixels", () => {
        begin();
        pointer(image, "pointerdown", 100, 100);
        pointer(image, "pointermove", 140, 120);
        expect(changes.at(-1)).toEqual({
            ...START,
            x: START.x + 40 * 32,
            y: START.y + 20 * 32,
        });
        expect(boxOfBounds(corners())).toEqual(changes.at(-1));
        pointer(image, "pointerup", 140, 120);
        expect(done).toEqual([changes.at(-1)]);
    });

    it("focuses the image on a press of the image or of a handle, so Escape reaches it", () => {
        document.body.append(map.getContainer());
        begin();
        pointer(image, "pointerdown", 100, 100);
        expect(document.activeElement).toBe(image);
        pointer(image, "pointerup", 100, 100);
        image.blur();
        pointer(handle("se"), "pointerdown", 0, 0);
        expect(document.activeElement).toBe(image);
    });

    it("measures a drag from where it started, not from the last move", () => {
        begin();
        pointer(image, "pointerdown", 100, 100);
        pointer(image, "pointermove", 110, 100);
        pointer(image, "pointermove", 140, 100);
        expect(changes.at(-1)?.x).toBe(START.x + 40 * 32);
    });

    it("does not persist a press that did not move", () => {
        begin();
        pointer(image, "pointerdown", 100, 100);
        pointer(image, "pointerup", 100, 100);
        expect(done).toEqual([]);
    });

    it("keeps the map still while the layer is dragged, and frees it after", () => {
        begin();
        expect(map.dragging.enabled()).toBe(true);
        pointer(image, "pointerdown", 100, 100);
        expect(map.dragging.enabled()).toBe(false);
        pointer(image, "pointerup", 100, 100);
        expect(map.dragging.enabled()).toBe(true);
    });

    it("leaves the map's dragging off when it was already off", () => {
        map.dragging.disable();
        begin();
        pointer(image, "pointerdown", 100, 100);
        pointer(image, "pointerup", 100, 100);
        expect(map.dragging.enabled()).toBe(false);
    });

    it("resizes from the south-east handle keeping the ratio, the north-west corner fixed", () => {
        begin();
        pointer(handle("se"), "pointerdown", 0, 0);
        pointer(handle("se"), "pointermove", 650, 360);
        const box = changes.at(-1)!;
        expect(box.x).toBe(START.x);
        expect(box.y).toBe(START.y);
        expect(box.w / box.h).toBeCloseTo(START.w / START.h);
        expect(box.w).toBeGreaterThan(START.w);
        pointer(handle("se"), "pointerup", 650, 360);
        expect(done).toEqual([box]);
    });

    it("frees the ratio with Shift", () => {
        begin();
        pointer(handle("se"), "pointerdown", 0, 0);
        pointer(handle("se"), "pointermove", 650, 360, { shiftKey: true });
        const box = changes.at(-1)!;
        expect(box.w / box.h).not.toBeCloseTo(START.w / START.h);
    });

    it("moves one screen pixel with an arrow and ten with Shift", () => {
        begin();
        key("keydown", "ArrowRight");
        expect(changes.at(-1)).toEqual({ ...START, x: START.x + 32 });
        key("keydown", "ArrowDown", { shiftKey: true });
        expect(changes.at(-1)?.y).toBe(START.y + 320);
        key("keydown", "ArrowLeft");
        key("keydown", "ArrowUp");
        expect(changes.at(-1)).toEqual({
            ...START,
            x: START.x,
            y: START.y + 320 - 32,
        });
    });

    it("takes the arrow's step from the map's zoom", () => {
        map.setView([-150, 150], 1, { animate: false });
        begin();
        key("keydown", "ArrowRight");
        expect(changes.at(-1)).toEqual({ ...START, x: START.x + 16 });
    });

    it("scales about the centre with plus and minus", () => {
        begin();
        key("keydown", "+");
        const up = changes.at(-1)!;
        expect(up.w).toBeCloseTo(START.w * 1.02);
        expect(up.x + up.w / 2).toBeCloseTo(START.x + START.w / 2);
        key("keydown", "-");
        expect(changes.at(-1)!.w).toBeCloseTo(START.w);
        key("keydown", "=");
        expect(changes.at(-1)!.w).toBeCloseTo(START.w * 1.02);
    });

    it("persists a keyboard change once, 200 ms after the last key goes up", () => {
        begin();
        key("keydown", "ArrowRight");
        key("keyup", "ArrowRight");
        key("keydown", "ArrowRight");
        key("keyup", "ArrowRight");
        vi.advanceTimersByTime(199);
        expect(done).toEqual([]);
        vi.advanceTimersByTime(1);
        expect(done).toEqual([{ ...START, x: START.x + 64 }]);
    });

    it("keeps the arrow keys from reaching the page", () => {
        begin();
        expect(key("keydown", "ArrowRight").defaultPrevented).toBe(true);
        expect(key("keydown", "a").defaultPrevented).toBe(false);
    });

    it("points the image at the element that explains the keys, and puts back what it found", () => {
        image.setAttribute("aria-describedby", "before");
        const adjusting = adjustLayer(map, layer, START, {
            label: LABEL,
            describedBy: "keys-help",
            onChange: () => {},
            onDone: () => {},
        });
        expect(image.getAttribute("aria-describedby")).toBe("keys-help");
        adjusting.stop();
        expect(image.getAttribute("aria-describedby")).toBe("before");
    });

    it("ends with Escape without keeping anything when nothing changed", () => {
        begin();
        key("keydown", "Escape");
        expect(done).toEqual([]);
        expect(exits).toBe(1);
    });

    it("ignores a second pointer going down mid-drag and frees the map at the end", () => {
        begin();
        pointer(image, "pointerdown", 100, 100);
        expect(map.dragging.enabled()).toBe(false);
        pointer(image, "pointerdown", 300, 300, { button: 0 });
        pointer(image, "pointerup", 100, 100);
        expect(map.dragging.enabled()).toBe(true);
    });

    it("ignores a press that is not the primary pointer's main button", () => {
        begin();
        const press = new MouseEvent("pointerdown", {
            bubbles: true,
            button: 2,
        });
        image.dispatchEvent(press);
        expect(map.dragging.enabled()).toBe(true);
        const touch = new MouseEvent("pointerdown", { bubbles: true });
        Object.defineProperty(touch, "isPrimary", { value: false });
        image.dispatchEvent(touch);
        expect(map.dragging.enabled()).toBe(true);
    });

    it("turns with [ and ] when the host handles turns", () => {
        const turns: number[] = [];
        adjustLayer(map, layer, START, {
            label: LABEL,
            onChange: () => {},
            onDone: () => {},
            onTurn: (by) => turns.push(by),
        });
        expect(key("keydown", "]").defaultPrevented).toBe(true);
        key("keydown", "[");
        expect(turns).toEqual([1, -1]);
    });

    it("ends with Escape: persists once, takes the handles away and says it ended", () => {
        begin();
        key("keydown", "ArrowRight");
        key("keyup", "ArrowRight");
        const escape = key("keydown", "Escape");
        expect(escape.defaultPrevented).toBe(true);
        expect(done).toEqual([{ ...START, x: START.x + 32 }]);
        vi.advanceTimersByTime(500);
        expect(done).toHaveLength(1);
        expect(exits).toBe(1);
        expect(layer.getPane()!.querySelector(".adjust-handle")).toBeNull();
        expect(image.hasAttribute("tabindex")).toBe(false);
        expect(image.hasAttribute("aria-label")).toBe(false);
        expect(image.classList).not.toContain("is-adjusting");
    });

    it("keeps the Escape from reaching the explorer's own handler", () => {
        const seen = vi.fn();
        document.body.append(map.getContainer());
        document.addEventListener("keydown", seen);
        begin();
        key("keydown", "Escape");
        document.removeEventListener("keydown", seen);
        expect(seen).not.toHaveBeenCalled();
    });

    it("stop() persists a pending keyboard change and says nothing of an exit", () => {
        const adjusting = begin();
        key("keydown", "ArrowRight");
        key("keyup", "ArrowRight");
        adjusting.stop();
        expect(done).toEqual([{ ...START, x: START.x + 32 }]);
        expect(exits).toBe(0);
    });

    it("stop() removes the listeners and the handles", () => {
        const adjusting = begin();
        adjusting.stop();
        const before = changes.length;
        pointer(image, "pointerdown", 100, 100);
        pointer(image, "pointermove", 140, 120);
        key("keydown", "ArrowRight");
        key("keydown", "Escape");
        expect(changes).toHaveLength(before);
        expect(done).toEqual([]);
        expect(map.dragging.enabled()).toBe(true);
        expect(layer.getPane()!.querySelector(".adjust-handle")).toBeNull();
        expect(image.classList).not.toContain("is-adjusting");
        adjusting.stop();
    });

    it("stop() in the middle of a drag frees the map", () => {
        const adjusting = begin();
        pointer(image, "pointerdown", 100, 100);
        adjusting.stop();
        expect(map.dragging.enabled()).toBe(true);
    });
});
