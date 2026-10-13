import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

const KEY_BOX = `<div data-ms-copy data-ms-copy-source=".value" data-ms-copy-text="ABCDEFGH">
  <code class="value">ABCD EFGH</code>
  <button type="button" data-ms-copy-button hidden data-copied="Copied">Copy</button>
  <span data-ms-copy-status role="status"></span></div>`;
const AREA_BOX = `<div data-ms-copy data-ms-copy-source="textarea">
  <textarea readonly>a@x.test\nb@x.test</textarea>
  <button type="button" data-ms-copy-button hidden data-copied="Copied">Copy</button>
  <span data-ms-copy-status role="status"></span></div>`;

async function load(html) {
    document.body.innerHTML = html;
    vi.resetModules();
    await import("./copy-text.js");
}

function clipboard(writeText) {
    Object.defineProperty(navigator, "clipboard", {
        value: writeText ? { writeText } : undefined,
        configurable: true,
    });
}

const $ = (sel) => document.querySelector(sel);

describe("copy-text", () => {
    beforeEach(() =>
        vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] }),
    );
    afterEach(() => {
        vi.useRealTimers();
        clipboard(undefined);
        window.getSelection().removeAllRanges();
    });

    it("reveals the button and copies data-ms-copy-text, not the shown text", async () => {
        const writeText = vi.fn(() => Promise.resolve());
        clipboard(writeText);
        await load(KEY_BOX);
        expect($("[data-ms-copy-button]").hidden).toBe(false);

        $("[data-ms-copy-button]").click();
        await vi.advanceTimersByTimeAsync(0);

        expect(writeText).toHaveBeenCalledWith("ABCDEFGH");
        expect($("[data-ms-copy-status]").textContent).toBe("Copied");
        vi.advanceTimersByTime(2500);
        expect($("[data-ms-copy-status]").textContent).toBe("");
    });

    it("copies the value of a form control", async () => {
        const writeText = vi.fn(() => Promise.resolve());
        clipboard(writeText);
        await load(AREA_BOX);

        $("[data-ms-copy-button]").click();
        await vi.advanceTimersByTimeAsync(0);

        expect(writeText).toHaveBeenCalledWith("a@x.test\nb@x.test");
        expect($("[data-ms-copy-status]").textContent).toBe("Copied");
    });

    it("selects the shown text when the Clipboard API is missing", async () => {
        clipboard(undefined);
        await load(KEY_BOX);

        $("[data-ms-copy-button]").click();

        expect(window.getSelection().toString()).toBe("ABCD EFGH");
        expect($("[data-ms-copy-status]").textContent).toBe("");
    });

    it("selects the control when the Clipboard API refuses", async () => {
        clipboard(vi.fn(() => Promise.reject(new Error("denied"))));
        await load(AREA_BOX);
        const area = $("textarea");

        $("[data-ms-copy-button]").click();
        await vi.advanceTimersByTimeAsync(0);

        expect(document.activeElement).toBe(area);
        expect(area.selectionEnd - area.selectionStart).toBe(area.value.length);
        expect($("[data-ms-copy-status]").textContent).toBe("");
    });

    it("leaves a page without a copy box alone", async () => {
        await load("<p>nothing</p>");
        expect($("p").textContent).toBe("nothing");
    });

    it("binds every box of the page", async () => {
        await load(KEY_BOX + AREA_BOX);
        const buttons = document.querySelectorAll("[data-ms-copy-button]");
        expect([...buttons].map((b) => b.hidden)).toEqual([false, false]);
    });
});
