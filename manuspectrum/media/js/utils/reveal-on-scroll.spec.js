import { describe, it, expect, beforeEach, vi } from "vitest";
import revealOnScroll from "./reveal-on-scroll";

let io;

class FakeIntersectionObserver {
    constructor(callback, options) {
        this.callback = callback;
        this.options = options;
        this.observed = [];
        this.unobserve = vi.fn();
        io = this;
    }
    observe(el) {
        this.observed.push(el);
    }
    disconnect() {}
}

function place(id, top, height = 100) {
    document.getElementById(id).getBoundingClientRect = () => ({
        top, bottom: top + height, left: 0, right: 100, width: 100, height,
    });
}

beforeEach(() => {
    document.body.innerHTML = `
        <div id="on" class="reveal"></div>
        <div id="edge" class="reveal"></div>
        <div id="below" class="reveal"></div>
        <div id="above" class="reveal"></div>
        <div id="scale" class="reveal-scale"></div>`;
    window.innerHeight = 800;
    window.innerWidth = 1200;
    place("on", 100);
    place("edge", 799);
    place("below", 1200);
    place("above", -500);
    place("scale", 1400);
    io = undefined;
    window.IntersectionObserver = FakeIntersectionObserver;
    globalThis.IntersectionObserver = FakeIntersectionObserver;
});

const cls = (id) => document.getElementById(id).classList;

describe("revealOnScroll", () => {
    it("shows an element on screen at start-up without hiding it", () => {
        revealOnScroll();
        expect(cls("on").contains("is-visible")).toBe(true);
        expect(cls("on").contains("is-pending")).toBe(false);
        expect(io.observed).not.toContain(document.getElementById("on"));
    });

    it("treats a single visible pixel as on screen", () => {
        revealOnScroll();
        expect(cls("edge").contains("is-visible")).toBe(true);
        expect(cls("edge").contains("is-pending")).toBe(false);
    });

    it("hides off-screen elements until they intersect", () => {
        revealOnScroll();
        const below = document.getElementById("below");
        expect(cls("below").contains("is-pending")).toBe(true);
        expect(cls("above").contains("is-pending")).toBe(true);
        io.callback([{ isIntersecting: true, target: below }]);
        expect(cls("below").contains("is-pending")).toBe(false);
        expect(cls("below").contains("is-visible")).toBe(true);
        expect(io.unobserve).toHaveBeenCalledWith(below);
    });

    it("ignores entries that are not intersecting", () => {
        revealOnScroll();
        io.callback([{ isIntersecting: false, target: document.getElementById("below") }]);
        expect(cls("below").contains("is-pending")).toBe(true);
    });

    it("reveals everything without IntersectionObserver", () => {
        delete window.IntersectionObserver;
        delete globalThis.IntersectionObserver;
        revealOnScroll();
        ["on", "below", "above"].forEach((id) => {
            expect(cls(id).contains("is-visible")).toBe(true);
            expect(cls(id).contains("is-pending")).toBe(false);
        });
    });

    it("uses .reveal only by default and accepts a wider selector", () => {
        revealOnScroll();
        expect(cls("scale").contains("is-pending")).toBe(false);
        revealOnScroll(0.06, { selector: ".reveal, .reveal-scale", rootMargin: "0px 0px -30px 0px" });
        expect(cls("scale").contains("is-pending")).toBe(true);
        expect(io.options).toEqual({ threshold: 0.06, rootMargin: "0px 0px -30px 0px" });
    });
});
