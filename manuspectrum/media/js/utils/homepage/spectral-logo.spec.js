import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import initSpectralLogo, { sampleCurve, readTable, toIntensity, toWavelength, X_MIN, X_MAX } from "./spectral-logo";

class FakePointerEvent extends MouseEvent {
    constructor(type, init = {}) {
        super(type, init);
        this.pointerType = init.pointerType || "mouse";
    }
}

function fakePath(points) {
    // Straight segments through the given points, parametrised by length.
    const segs = [];
    let total = 0;
    for (let i = 1; i < points.length; i++) {
        const [a, b] = [points[i - 1], points[i]];
        const len = Math.hypot(b.x - a.x, b.y - a.y);
        segs.push({ a, b, start: total, len });
        total += len;
    }
    return {
        getTotalLength: () => total,
        getPointAtLength: (s) => {
            const seg = segs.find((g) => s <= g.start + g.len) || segs[segs.length - 1];
            const t = seg.len ? Math.min(1, Math.max(0, (s - seg.start) / seg.len)) : 0;
            return { x: seg.a.x + t * (seg.b.x - seg.a.x), y: seg.a.y + t * (seg.b.y - seg.a.y) };
        },
    };
}

describe("sampling", () => {
    it("interpolates between samples and holds the last y past the end", () => {
        const table = sampleCurve(fakePath([{ x: 40, y: 80 }, { x: 140, y: 30 }, { x: 452, y: 30 }]));
        expect(table.length).toBe(X_MAX - X_MIN + 1);
        expect(readTable(table, 40)).toBeCloseTo(80, 1);
        expect(readTable(table, 90)).toBeCloseTo(55, 1);
        expect(readTable(table, 90.5)).toBeCloseTo(54.75, 1);
        expect(readTable(table, 600)).toBeCloseTo(30, 5);
    });

    it("maps y to intensity and x to wavelength", () => {
        expect(toIntensity(82)).toBe(0);
        expect(toIntensity(4)).toBe(1);
        expect(toIntensity(200)).toBe(0);
        expect(toWavelength(40)).toBe(380);
        expect(toWavelength(620)).toBe(780);
    });
});

describe("crosshair and zoom", () => {
    let destroy;

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal("requestAnimationFrame", (cb) => setTimeout(cb, 16));
        vi.stubGlobal("cancelAnimationFrame", (id) => clearTimeout(id));
        HTMLDialogElement.prototype.showModal = function showModal() {
            this.setAttribute("open", "");
        };
        HTMLDialogElement.prototype.close = function close() {
            this.removeAttribute("open");
            this.dispatchEvent(new Event("close"));
        };
        document.body.innerHTML = `
            <div id="ms-logo-wrap">
                <svg id="ms-logo-svg">
                    <path id="curve-blue"></path><path id="curve-red"></path>
                    <g id="ms-logo-crosshair" display="none">
                        <line id="ms-cross-v"></line><line id="ms-cross-h-blue"></line><line id="ms-cross-h-red"></line>
                        <circle id="ms-dot-blue"></circle><circle id="ms-dot-red"></circle>
                    </g>
                    <g id="ms-logo-tooltip" display="none">
                        <rect id="ms-tt-bg"></rect><text id="ms-tt-wl"></text><text id="ms-tt-blue"></text><text id="ms-tt-red"></text>
                    </g>
                </svg>
                <button type="button" id="ms-logo-zoom"></button>
            </div>
            <dialog class="ms-logo-dialog" id="ms-logo-dialog">
                <div class="ms-logo-overlay-inner">
                    <button type="button" id="ms-logo-close"></button>
                    <div id="ms-logo-zoom-target"></div>
                </div>
            </dialog>`;
        const svg = document.getElementById("ms-logo-svg");
        Object.assign(document.getElementById("curve-blue"), fakePath([{ x: 40, y: 80 }, { x: 452, y: 20 }]));
        Object.assign(document.getElementById("curve-red"), fakePath([{ x: 40, y: 70 }, { x: 458, y: 40 }]));
        svg.createSVGPoint = () => ({
            x: 0,
            y: 0,
            matrixTransform() {
                return { x: this.x, y: this.y };
            },
        });
        svg.getScreenCTM = () => ({ inverse: () => ({}) });
        destroy = initSpectralLogo(document);
    });

    afterEach(() => {
        destroy();
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    const move = (type, clientX) =>
        document.getElementById("ms-logo-svg").dispatchEvent(new FakePointerEvent(type, { clientX, clientY: 40, bubbles: true }));
    const shown = (id) => document.getElementById(id).getAttribute("display") !== "none";

    it("shows the crosshair and formats the tooltip on the next frame", () => {
        move("pointermove", 246);
        expect(shown("ms-logo-crosshair")).toBe(false);
        vi.advanceTimersByTime(16);
        expect(shown("ms-logo-crosshair")).toBe(true);
        expect(document.getElementById("ms-tt-wl").textContent).toBe(`λ = ${Math.round(toWavelength(246))} nm`);
        expect(document.getElementById("ms-tt-blue").textContent).toMatch(/^● I₁ = \d\.\d{3}$/);
    });

    it("cancels a pending frame when the pointer leaves", () => {
        move("pointermove", 246);
        move("pointerleave", 246);
        vi.advanceTimersByTime(32);
        expect(shown("ms-logo-crosshair")).toBe(false);
        expect(shown("ms-logo-tooltip")).toBe(false);
    });

    it("hides outside the plot range", () => {
        move("pointermove", 246);
        vi.advanceTimersByTime(16);
        move("pointermove", 10);
        expect(shown("ms-logo-crosshair")).toBe(false);
    });

    it("moves the logo into the dialog and back, returning focus", () => {
        const svg = document.getElementById("ms-logo-svg");
        const zoom = document.getElementById("ms-logo-zoom");
        zoom.click();
        expect(document.getElementById("ms-logo-dialog").hasAttribute("open")).toBe(true);
        expect(document.getElementById("ms-logo-zoom-target").contains(svg)).toBe(true);
        expect(svg.classList.contains("is-drawn")).toBe(true);
        document.getElementById("ms-logo-close").click();
        expect(document.getElementById("ms-logo-wrap").firstElementChild).toBe(svg);
        expect(document.activeElement).toBe(zoom);
    });

    it("closes on a click that starts and ends on the backdrop only", () => {
        const dialog = document.getElementById("ms-logo-dialog");
        document.getElementById("ms-logo-zoom").click();
        const inner = dialog.querySelector(".ms-logo-overlay-inner");
        inner.dispatchEvent(new FakePointerEvent("pointerdown", { bubbles: true }));
        dialog.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        expect(dialog.hasAttribute("open")).toBe(true);
        dialog.dispatchEvent(new FakePointerEvent("pointerdown", { bubbles: true }));
        dialog.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        expect(dialog.hasAttribute("open")).toBe(false);
    });
});

describe("zoom fallback", () => {
    it("hides the zoom button when the dialog has no showModal", () => {
        const original = HTMLDialogElement.prototype.showModal;
        delete HTMLDialogElement.prototype.showModal;
        document.body.innerHTML = `
            <div id="ms-logo-wrap">
                <svg id="ms-logo-svg"></svg>
                <button type="button" id="ms-logo-zoom"></button>
            </div>
            <dialog id="ms-logo-dialog">
                <div id="ms-logo-zoom-target"></div>
            </dialog>`;
        const destroy = initSpectralLogo(document);
        expect(document.getElementById("ms-logo-zoom").hidden).toBe(true);
        destroy();
        if (original) {
            HTMLDialogElement.prototype.showModal = original;
        }
    });
});
