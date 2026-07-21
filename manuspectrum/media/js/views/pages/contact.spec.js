// Behavioural spec for the contact form: per-field validation with ARIA
// wiring, the live character counter, the copy-address escape hatch and the
// "no address configured" degraded state. The mailto: navigation itself is
// jsdom's blind spot (Location is non-configurable), so the submit test
// asserts the observable DOM outcome instead.

import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("utils/ms-nav", () => ({ default: () => {} }));

const PAGE = (email) => `
<form class="ms-contact-form" id="ms-contact-form" data-contact-email="${email}" novalidate>
    <input type="text" id="cf-name" name="name" required aria-describedby="cf-name-err">
    <p id="cf-name-err" hidden></p>
    <input type="email" id="cf-email" name="email" required aria-describedby="cf-email-err">
    <p id="cf-email-err" hidden></p>
    <select id="cf-type" name="type"><option value="project" selected>Submit a project</option></select>
    <textarea id="cf-message" name="message" maxlength="1600" required aria-describedby="cf-message-err ms-contact-count"></textarea>
    <p id="ms-contact-count"></p>
    <p id="cf-message-err" hidden></p>
    <p id="ms-contact-error" role="alert" hidden></p>
    <button type="submit" id="ms-contact-submit">Open my email app</button>
    <p id="ms-contact-note" hidden>No address yet.</p>
    <div id="ms-contact-direct">
        <span class="ms-contact-address" id="ms-contact-address">${email}</span>
        <button type="button" class="ms-contact-copy" id="ms-contact-copy-address" data-copy-target="ms-contact-address">Copy</button>
        <span id="ms-contact-copied" role="status"></span>
    </div>
</form>`;

async function boot(email = "team@manuspectrum.fr") {
    document.body.innerHTML = PAGE(email);
    vi.resetModules();
    await import("./contact");
    document.dispatchEvent(new Event("DOMContentLoaded"));
}

beforeEach(() => {
    vi.restoreAllMocks();
});

describe("contact form validation", () => {
    it("flags every empty required field with its own ARIA-wired error", async () => {
        await boot();
        document
            .getElementById("ms-contact-form")
            .dispatchEvent(new Event("submit", { cancelable: true }));
        const name = document.getElementById("cf-name");
        expect(name.getAttribute("aria-invalid")).toBe("true");
        expect(document.getElementById("cf-name-err").hidden).toBe(false);
        expect(document.getElementById("cf-name-err").textContent).not.toBe("");
        expect(document.getElementById("cf-email-err").hidden).toBe(false);
        expect(document.getElementById("cf-message-err").hidden).toBe(false);
        expect(document.getElementById("ms-contact-error").hidden).toBe(false);
        // focus moves to the first invalid control
        expect(document.activeElement).toBe(name);
    });

    it("rejects an invalid email but accepts a valid one", async () => {
        await boot();
        document.getElementById("cf-name").value = "Ada";
        document.getElementById("cf-email").value = "not-an-email";
        document.getElementById("cf-message").value = "Hello";
        document
            .getElementById("ms-contact-form")
            .dispatchEvent(new Event("submit", { cancelable: true }));
        expect(
            document.getElementById("cf-email").getAttribute("aria-invalid"),
        ).toBe("true");
        expect(
            document.getElementById("cf-name").hasAttribute("aria-invalid"),
        ).toBe(false);
    });

    it("clears a field's error as soon as the user types", async () => {
        await boot();
        const form = document.getElementById("ms-contact-form");
        form.dispatchEvent(new Event("submit", { cancelable: true }));
        const name = document.getElementById("cf-name");
        expect(name.getAttribute("aria-invalid")).toBe("true");
        name.value = "A";
        name.dispatchEvent(new Event("input"));
        expect(name.hasAttribute("aria-invalid")).toBe(false);
        expect(document.getElementById("cf-name-err").hidden).toBe(true);
    });

    it("hides the error summary on a fully valid submit", async () => {
        await boot();
        document.getElementById("cf-name").value = "Ada";
        document.getElementById("cf-email").value = "ada@example.org";
        document.getElementById("cf-message").value = "Hello there";
        document
            .getElementById("ms-contact-form")
            .dispatchEvent(new Event("submit", { cancelable: true }));
        expect(document.getElementById("ms-contact-error").hidden).toBe(true);
        expect(
            document.getElementById("cf-name").hasAttribute("aria-invalid"),
        ).toBe(false);
    });
});

describe("character counter", () => {
    it("counts down from maxlength and flags the low state", async () => {
        await boot();
        const msg = document.getElementById("cf-message");
        const count = document.getElementById("ms-contact-count");
        expect(count.textContent).toContain("1600");
        msg.value = "x".repeat(1550);
        msg.dispatchEvent(new Event("input"));
        expect(count.textContent).toContain("50");
        expect(count.classList.contains("is-low")).toBe(true);
    });
});

describe("copy escape hatch", () => {
    it("copies the address and announces it", async () => {
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(window, "isSecureContext", {
            value: true,
            configurable: true,
        });
        Object.defineProperty(window.navigator, "clipboard", {
            value: { writeText },
            configurable: true,
        });
        await boot();
        document.getElementById("ms-contact-copy-address").click();
        await Promise.resolve();
        expect(writeText).toHaveBeenCalledWith("team@manuspectrum.fr");
        expect(
            document.getElementById("ms-contact-copied").textContent,
        ).not.toBe("");
    });
});

describe("no configured address", () => {
    it("disables the button, shows the note, hides the direct row", async () => {
        await boot("");
        expect(document.getElementById("ms-contact-submit").disabled).toBe(
            true,
        );
        expect(document.getElementById("ms-contact-note").hidden).toBe(false);
        expect(document.getElementById("ms-contact-direct").hidden).toBe(true);
    });
});
