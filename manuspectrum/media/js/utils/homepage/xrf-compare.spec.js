import { describe, it, expect, beforeEach } from "vitest";
import initXrfCompare from "./xrf-compare";

class FakePointerEvent extends MouseEvent {
    constructor(type, init = {}) {
        super(type, init);
        this.pointerType = init.pointerType || "mouse";
    }
}

let box;
let range;

function pointer(type, clientX, pointerType = "mouse") {
    box.dispatchEvent(new FakePointerEvent(type, { clientX, pointerType, bubbles: true }));
}

beforeEach(() => {
    document.body.innerHTML = `
        <div id="ms-xrf-compare" class="ms-gallery-compare">
            <div class="ms-compare-divider" aria-hidden="true"></div>
            <input type="range" class="ms-compare-range ms-visually-hidden" min="0" max="100" value="100">
        </div>
        <button id="elsewhere"></button>`;
    box = document.getElementById("ms-xrf-compare");
    range = box.querySelector(".ms-compare-range");
    box.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100 });
    initXrfCompare(document);
});

const split = () => box.style.getPropertyValue("--split");

describe("XRF comparison", () => {
    it("writes the split with its percent unit from the range", () => {
        range.value = "40";
        range.dispatchEvent(new Event("input", { bubbles: true }));
        expect(split()).toBe("40%");
        expect(box.classList.contains("is-comparing")).toBe(true);
    });

    it("follows the mouse and keeps the range in step", () => {
        pointer("pointermove", 50);
        expect(split()).toBe("25%");
        expect(range.value).toBe("25");
    });

    it("resets to 100 when the mouse leaves", () => {
        pointer("pointermove", 50);
        pointer("pointerleave", 250);
        expect(split()).toBe("100%");
        expect(box.classList.contains("is-comparing")).toBe(false);
    });

    it("keeps the split on leave while the range has focus", () => {
        range.focus();
        pointer("pointermove", 50);
        pointer("pointerleave", 250);
        expect(split()).toBe("25%");
    });

    it("ignores a touch move that is not pressed", () => {
        pointer("pointermove", 50, "touch");
        expect(split()).toBe("");
    });

    it("sets the split on a tap and keeps it after the finger lifts", () => {
        pointer("pointerdown", 100, "touch");
        pointer("pointermove", 60, "touch");
        pointer("pointerup", 60, "touch");
        pointer("pointerleave", 60, "touch");
        expect(split()).toBe("30%");
    });
});
