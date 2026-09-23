import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import initShowcaseCarousel from "./showcase-carousel";

let io;

class FakeIntersectionObserver {
    constructor(callback, options) {
        this.callback = callback;
        this.options = options;
        io = this;
    }
    observe() {}
    disconnect() {}
}

function boot({ reduce = false } = {}) {
    document.body.innerHTML = `
        <div id="ms-showcase">
            <div id="ms-showcase-track">
                <div class="ms-showcase-slide"></div>
                <div class="ms-showcase-slide"></div>
                <div class="ms-showcase-slide"></div>
            </div>
            <button type="button" id="ms-showcase-prev"></button>
            <button type="button" id="ms-showcase-next"></button>
            <div id="ms-showcase-nav">
                <button type="button" class="ms-showcase-dot active" aria-current="true"></button>
                <button type="button" class="ms-showcase-dot"></button>
                <button type="button" class="ms-showcase-dot"></button>
            </div>
        </div>`;
    const track = document.getElementById("ms-showcase-track");
    Array.from(track.children).forEach((slide, i) => {
        Object.defineProperty(slide, "offsetLeft", { value: i * 1000 });
    });
    Object.defineProperty(track, "offsetLeft", { value: 0 });
    track.scrollTo = vi.fn();
    window.matchMedia = vi.fn().mockReturnValue({ matches: reduce });
    window.IntersectionObserver = FakeIntersectionObserver;
    globalThis.IntersectionObserver = FakeIntersectionObserver;
    const destroy = initShowcaseCarousel(document);
    return { track, destroy };
}

const dots = () => Array.from(document.querySelectorAll(".ms-showcase-dot"));
const activeIndex = () => dots().findIndex((d) => d.getAttribute("aria-current") === "true");

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("showcase carousel", () => {
    it("advances twice on two quick clicks", () => {
        const { track } = boot();
        document.getElementById("ms-showcase-next").click();
        document.getElementById("ms-showcase-next").click();
        expect(activeIndex()).toBe(2);
        expect(track.scrollTo).toHaveBeenLastCalledWith({ left: 2000, behavior: "smooth" });
    });

    it("wraps around both ways", () => {
        boot();
        document.getElementById("ms-showcase-prev").click();
        expect(activeIndex()).toBe(2);
        document.getElementById("ms-showcase-next").click();
        expect(activeIndex()).toBe(0);
    });

    it("jumps to a dot's slide and marks only that dot", () => {
        boot();
        dots()[1].click();
        expect(activeIndex()).toBe(1);
        expect(dots().filter((d) => d.classList.contains("active"))).toEqual([dots()[1]]);
    });

    it("scrolls instantly under reduced motion", () => {
        const { track } = boot({ reduce: true });
        document.getElementById("ms-showcase-next").click();
        expect(track.scrollTo).toHaveBeenLastCalledWith({ left: 1000, behavior: "instant" });
    });

    it("follows manual scrolling from a 0.6 ratio", () => {
        const { track } = boot();
        const slides = Array.from(track.children);
        io.callback([{ target: slides[2], intersectionRatio: 0.4, isIntersecting: true }]);
        expect(activeIndex()).toBe(0);
        io.callback([{ target: slides[2], intersectionRatio: 0.7, isIntersecting: true }]);
        expect(activeIndex()).toBe(2);
        expect(io.options).toEqual({ root: track, threshold: 0.6 });
    });

    it("ignores the observer during a programmed scroll", () => {
        const { track } = boot();
        const slides = Array.from(track.children);
        document.getElementById("ms-showcase-next").click();
        io.callback([{ target: slides[0], intersectionRatio: 0.9, isIntersecting: true }]);
        expect(activeIndex()).toBe(1);
        vi.advanceTimersByTime(600);
        io.callback([{ target: slides[0], intersectionRatio: 0.9, isIntersecting: true }]);
        expect(activeIndex()).toBe(0);
    });

    it("ends the programmed scroll on scrollend", () => {
        const { track } = boot();
        const slides = Array.from(track.children);
        document.getElementById("ms-showcase-next").click();
        track.dispatchEvent(new Event("scrollend"));
        io.callback([{ target: slides[2], intersectionRatio: 0.9, isIntersecting: true }]);
        expect(activeIndex()).toBe(2);
    });
});
