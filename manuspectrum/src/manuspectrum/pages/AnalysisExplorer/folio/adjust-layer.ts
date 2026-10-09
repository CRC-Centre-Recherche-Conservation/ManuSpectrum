import L from "leaflet";

import { ANNOTATION_SCALE } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import {
    boundsOfBox,
    moveBox,
    resizeFromCorner,
    scaleBox,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";

import type {
    Box,
    Corner,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";

const CORNERS: readonly Corner[] = ["nw", "ne", "se", "sw"];
const HANDLE_SIZE = "1.25rem";
const HANDLE_OFFSET = "-0.625rem";
const SCALE_STEP = 1.02;
const BIG_STEP = 10;
const PERSIST_DELAY_MS = 200;
const ADJUSTING_CLASS = "is-adjusting";

export interface AdjustOptions {
    /** The complete accessible name of the image while it is adjusted. */
    label: string;
    /** Called on every change, once the layer has been redrawn. */
    onChange(box: Box): void;
    /** Called when a change is to be kept: pointer up, a pause in the keys, Escape, `stop()` with one pending. */
    onDone(box: Box): void;
    /** Called when the reader ends the adjustment with Escape; not by `stop()`. */
    onExit?(): void;
}

/**
 * Moves and resizes a laid image overlay on `map`, from its box `start` in
 * annotation pixels (`registration.ts`). A pointer drag of the image moves it,
 * a drag of one of four corner handles resizes it about the opposite corner
 * (the ratio kept unless Shift is held); with the image focused, the arrows
 * move it by one screen pixel (ten with Shift), `+` and `-` scale it about its
 * centre, and Escape ends the adjustment. The layer is redrawn as the box
 * changes; `onDone` is the moment to keep it. The map does not pan while a
 * drag runs; a press on the image or a handle focuses the image, so the keys
 * (and Escape) reach it. `stop()` leaves the image as it was found.
 */
export function adjustLayer(
    map: L.Map,
    layer: L.ImageOverlay,
    start: Box,
    options: AdjustOptions,
): { stop(): void } {
    const image = layer.getElement() as HTMLImageElement;
    const pane = layer.getPane() as HTMLElement;
    const handles = new Map<Corner, HTMLElement>();
    const hadTabindex = image.getAttribute("tabindex");
    const hadLabel = image.getAttribute("aria-label");
    const hadPointerEvents = image.style.pointerEvents;
    let box = start;
    let drag: { release: () => void } | null = null;
    let wasDraggable = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let pending = false;
    let stopped = false;

    /** The annotation pixels under a client position. */
    function annotationAt(event: MouseEvent): { x: number; y: number } {
        const at = map.mouseEventToLatLng(event);
        return { x: at.lng * ANNOTATION_SCALE, y: -at.lat * ANNOTATION_SCALE };
    }

    function placeHandles(): void {
        const corners: Record<Corner, [number, number]> = {
            nw: [box.x, box.y],
            ne: [box.x + box.w, box.y],
            se: [box.x + box.w, box.y + box.h],
            sw: [box.x, box.y + box.h],
        };
        for (const [corner, element] of handles) {
            const [x, y] = corners[corner];
            L.DomUtil.setPosition(
                element,
                map.latLngToLayerPoint([
                    -y / ANNOTATION_SCALE,
                    x / ANNOTATION_SCALE,
                ]),
            );
        }
    }

    function change(next: Box): void {
        box = next;
        layer.setBounds(L.latLngBounds(boundsOfBox(box)));
        placeHandles();
        options.onChange(box);
    }

    function persist(): void {
        if (timer !== null) clearTimeout(timer);
        timer = null;
        pending = false;
        options.onDone(box);
    }

    function freeze(event: PointerEvent): void {
        wasDraggable = map.dragging.enabled();
        map.dragging.disable();
        let captured = false;
        try {
            (event.target as Element).setPointerCapture?.(event.pointerId);
            captured = true;
        } catch {
            captured = false;
        }
        const target = event.target as Element;
        drag = {
            release() {
                if (captured) {
                    try {
                        target.releasePointerCapture?.(event.pointerId);
                    } catch {
                        // The capture is already gone.
                    }
                }
                if (wasDraggable) map.dragging.enable();
            },
        };
    }

    function endDrag(): void {
        drag?.release();
        drag = null;
    }

    /** Runs `move` for each pointer move until the pointer goes up or is cancelled. */
    function track(
        event: PointerEvent,
        target: HTMLElement,
        move: (event: PointerEvent) => Box,
    ): void {
        event.preventDefault();
        event.stopPropagation();
        image.focus({ preventScroll: true });
        freeze(event);
        let moved = false;
        function onMove(next: Event): void {
            moved = true;
            change(move(next as PointerEvent));
        }
        function onEnd(): void {
            target.removeEventListener("pointermove", onMove);
            target.removeEventListener("pointerup", onEnd);
            target.removeEventListener("pointercancel", onEnd);
            releases.delete(onEnd);
            endDrag();
            if (moved) persist();
        }
        target.addEventListener("pointermove", onMove);
        target.addEventListener("pointerup", onEnd);
        target.addEventListener("pointercancel", onEnd);
        releases.add(onEnd);
    }

    const releases = new Set<() => void>();

    function onImageDown(event: Event): void {
        const down = event as PointerEvent;
        const origin = annotationAt(down);
        const from = box;
        track(down, image, (next) => {
            const at = annotationAt(next);
            return moveBox(from, at.x - origin.x, at.y - origin.y);
        });
    }

    function onHandleDown(corner: Corner, event: Event): void {
        const down = event as PointerEvent;
        const from = box;
        track(down, handles.get(corner)!, (next) =>
            resizeFromCorner(from, corner, annotationAt(next), !next.shiftKey),
        );
    }

    /** A screen-pixel step, in annotation pixels, at the map's zoom. */
    function screenStep(dx: number, dy: number): { x: number; y: number } {
        const origin = L.point(map.getSize().x / 2, map.getSize().y / 2);
        const a = map.containerPointToLatLng(origin);
        const b = map.containerPointToLatLng(origin.add([dx, dy]));
        return {
            x: (b.lng - a.lng) * ANNOTATION_SCALE,
            y: -(b.lat - a.lat) * ANNOTATION_SCALE,
        };
    }

    function onKeyDown(event: Event): void {
        const key = event as KeyboardEvent;
        const step = key.shiftKey ? BIG_STEP : 1;
        const arrows: Record<string, [number, number]> = {
            ArrowLeft: [-step, 0],
            ArrowRight: [step, 0],
            ArrowUp: [0, -step],
            ArrowDown: [0, step],
        };
        if (key.key === "Escape") {
            key.preventDefault();
            key.stopPropagation();
            persist();
            stop();
            options.onExit?.();
            return;
        }
        const arrow = arrows[key.key];
        if (arrow) {
            const by = screenStep(arrow[0], arrow[1]);
            change(moveBox(box, by.x, by.y));
        } else if (key.key === "+" || key.key === "=") {
            change(scaleBox(box, SCALE_STEP, "centre"));
        } else if (key.key === "-") {
            change(scaleBox(box, 1 / SCALE_STEP, "centre"));
        } else {
            return;
        }
        key.preventDefault();
        key.stopPropagation();
        pending = true;
    }

    function onKeyUp(event: Event): void {
        if (!pending) return;
        event.stopPropagation();
        if (timer !== null) clearTimeout(timer);
        timer = setTimeout(persist, PERSIST_DELAY_MS);
    }

    function onDoubleClick(event: Event): void {
        event.stopPropagation();
    }

    function stop(): void {
        if (stopped) return;
        stopped = true;
        if (pending) persist();
        for (const release of [...releases]) release();
        endDrag();
        map.off("zoom move viewreset zoomend moveend", placeHandles);
        image.removeEventListener("pointerdown", onImageDown);
        image.removeEventListener("keydown", onKeyDown);
        image.removeEventListener("keyup", onKeyUp);
        image.removeEventListener("dblclick", onDoubleClick);
        for (const element of handles.values()) element.remove();
        handles.clear();
        image.classList.remove(ADJUSTING_CLASS);
        image.style.pointerEvents = hadPointerEvents;
        restore("tabindex", hadTabindex);
        restore("aria-label", hadLabel);
    }

    function restore(name: string, value: string | null): void {
        if (value === null) image.removeAttribute(name);
        else image.setAttribute(name, value);
    }

    image.setAttribute("tabindex", "0");
    image.setAttribute("aria-label", options.label);
    image.classList.add(ADJUSTING_CLASS);
    image.style.pointerEvents = "auto";
    image.addEventListener("pointerdown", onImageDown);
    image.addEventListener("keydown", onKeyDown);
    image.addEventListener("keyup", onKeyUp);
    image.addEventListener("dblclick", onDoubleClick);
    for (const corner of CORNERS) {
        const element = L.DomUtil.create("div", "adjust-handle", pane);
        element.dataset.corner = corner;
        element.style.pointerEvents = "auto";
        element.style.width = HANDLE_SIZE;
        element.style.height = HANDLE_SIZE;
        element.style.margin = `${HANDLE_OFFSET} 0 0 ${HANDLE_OFFSET}`;
        element.addEventListener("pointerdown", (event) =>
            onHandleDown(corner, event),
        );
        element.addEventListener("dblclick", onDoubleClick);
        handles.set(corner, element);
    }
    placeHandles();
    map.on("zoom move viewreset zoomend moveend", placeHandles);
    image.focus({ preventScroll: true });

    return { stop };
}
