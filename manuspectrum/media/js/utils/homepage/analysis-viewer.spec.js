import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import initAnalysisViewer from "./analysis-viewer";

let destroy;

beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("requestAnimationFrame", (cb) => setTimeout(cb, 0));
    vi.stubGlobal("cancelAnimationFrame", (id) => clearTimeout(id));
    document.body.innerHTML = `
        <div id="ms-analysis-viewer">
            <button type="button" class="ms-analysis-point" aria-controls="ms-analysis-popup-1" aria-expanded="false"></button>
            <button type="button" class="ms-analysis-point" aria-controls="ms-analysis-popup-2" aria-expanded="false"></button>
            <div class="ms-analysis-popup" id="ms-analysis-popup-1" hidden></div>
            <div class="ms-analysis-popup" id="ms-analysis-popup-2" hidden></div>
        </div>
        <button id="outside"></button>`;
    const viewer = document.getElementById("ms-analysis-viewer");
    viewer.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 600, right: 800, bottom: 600 });
    document.querySelectorAll(".ms-analysis-point").forEach((p, i) => {
        p.getBoundingClientRect = () => ({ left: 300 + i * 50, top: 100, width: 14, height: 14, right: 314 + i * 50, bottom: 114 });
    });
    document.querySelectorAll(".ms-analysis-popup").forEach((popup) => {
        Object.defineProperty(popup, "offsetWidth", { get: () => (popup.hidden ? 0 : 260) });
        Object.defineProperty(popup, "offsetHeight", { get: () => (popup.hidden ? 0 : 210) });
    });
    destroy = initAnalysisViewer(document);
});

afterEach(() => {
    destroy();
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

const point = (n) => document.querySelectorAll(".ms-analysis-point")[n - 1];
const popup = (n) => document.getElementById(`ms-analysis-popup-${n}`);

describe("analysis viewer", () => {
    it("un-hides before measuring, then activates on the next frame", () => {
        point(1).click();
        expect(popup(1).hidden).toBe(false);
        // Measured while visible: 300 + 14/2 - 260/2. Measuring while hidden would give 307px.
        expect(popup(1).style.left).toBe("177px");
        expect(popup(1).style.top).toBe(`${114 + 8}px`);
        expect(popup(1).classList.contains("active")).toBe(false);
        vi.advanceTimersByTime(0);
        expect(popup(1).classList.contains("active")).toBe(true);
        expect(point(1).getAttribute("aria-expanded")).toBe("true");
        expect(document.getElementById("ms-analysis-viewer").classList.contains("has-popup")).toBe(true);
    });

    it("closes on a second click and hides after the fade", () => {
        point(1).click();
        vi.advanceTimersByTime(0);
        point(1).click();
        expect(popup(1).classList.contains("active")).toBe(false);
        expect(popup(1).hidden).toBe(false);
        vi.advanceTimersByTime(350);
        expect(popup(1).hidden).toBe(true);
        expect(point(1).getAttribute("aria-expanded")).toBe("false");
    });

    it("hides on transitionend of opacity", () => {
        point(1).click();
        vi.advanceTimersByTime(0);
        point(1).click();
        const end = new Event("transitionend");
        end.propertyName = "opacity";
        popup(1).dispatchEvent(end);
        expect(popup(1).hidden).toBe(true);
    });

    it("stays open when reopened during the fade-out", () => {
        point(1).click();
        vi.advanceTimersByTime(0);
        point(1).click();
        point(1).click();
        vi.advanceTimersByTime(400);
        expect(popup(1).hidden).toBe(false);
        expect(popup(1).classList.contains("active")).toBe(true);
    });

    it("keeps one popup open at a time", () => {
        point(1).click();
        point(2).click();
        vi.advanceTimersByTime(400);
        expect(popup(1).hidden).toBe(true);
        expect(popup(2).hidden).toBe(false);
    });

    it("closes on Escape and on an outside click", () => {
        point(1).click();
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
        expect(point(1).getAttribute("aria-expanded")).toBe("false");
        point(2).click();
        document.getElementById("outside").click();
        expect(point(2).getAttribute("aria-expanded")).toBe("false");
    });

    it("does not close when the opening click reaches the document", () => {
        point(1).click();
        expect(point(1).getAttribute("aria-expanded")).toBe("true");
    });
});
