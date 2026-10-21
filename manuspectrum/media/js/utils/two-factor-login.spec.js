import { describe, it, expect, afterEach, vi } from "vitest";

const CORE_FORM = `<form name="two-factor-authentication-form" action="/en/two-factor-authentication-login" method="post">
  <input id="two-factor-authentication" name="two-factor-authentication" type="text"
    onkeyup="(function(input){
        if (input.value.length == 6) {
            document.forms['two-factor-authentication-form'].submit();
        }
    })(this)" />
</form>`;

let posts;

async function mount(withScript) {
    document.body.innerHTML = CORE_FORM;
    const form = document.forms["two-factor-authentication-form"];
    posts = 0;
    form.submit = () => {
        posts += 1;
    };
    if (withScript) {
        vi.resetModules();
        await import("./two-factor-login.js");
    }
    form.addEventListener("submit", (event) => {
        if (!event.defaultPrevented) {
            posts += 1;
        }
        event.preventDefault();
    });
    return form;
}

function type(input, value) {
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true }));
}

function core(input) {
    input.onkeyup = () => {
        if (input.value.length == 6) {
            document.forms["two-factor-authentication-form"].submit();
        }
    };
}

describe("two-factor-login", () => {
    afterEach(() => {
        document.body.innerHTML = "";
        vi.restoreAllMocks();
    });

    it("the core markup alone submits on every key release", async () => {
        const form = await mount(false);
        const input = form.elements["two-factor-authentication"];
        core(input);
        input.value = "123456";
        input.dispatchEvent(new KeyboardEvent("keyup"));
        input.dispatchEvent(new KeyboardEvent("keyup"));
        expect(posts).toBe(2);
    });

    it("submits once however many key releases follow six digits", async () => {
        const form = await mount(true);
        const input = form.elements["two-factor-authentication"];
        expect(input.hasAttribute("onkeyup")).toBe(false);
        type(input, "12345");
        expect(posts).toBe(0);
        type(input, "123456");
        type(input, "123456");
        input.dispatchEvent(new KeyboardEvent("keyup"));
        expect(posts).toBe(1);
        expect(input.readOnly).toBe(true);
        expect(input.disabled).toBe(false);
    });

    it("submits once for an autofilled code (input event only)", async () => {
        const form = await mount(true);
        const input = form.elements["two-factor-authentication"];
        input.value = "654321";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("input", { bubbles: true }));
        expect(posts).toBe(1);
    });

    it("does not submit a seven-digit or non-numeric value", async () => {
        const form = await mount(true);
        const input = form.elements["two-factor-authentication"];
        type(input, "1234567");
        type(input, "12345a");
        expect(posts).toBe(0);
    });

    it("prevents a later Enter after the submission", async () => {
        const form = await mount(true);
        const input = form.elements["two-factor-authentication"];
        type(input, "123456");
        const again = new Event("submit", { cancelable: true, bubbles: true });
        form.dispatchEvent(again);
        expect(again.defaultPrevented).toBe(true);
        expect(posts).toBe(1);
    });

    it("makes the form usable again when the page returns from the back/forward cache", async () => {
        const form = await mount(true);
        const input = form.elements["two-factor-authentication"];
        type(input, "123456");
        expect(input.readOnly).toBe(true);
        expect(form.dataset.msSubmitted).toBe("1");

        const restored = new Event("pageshow");
        restored.persisted = true;
        window.dispatchEvent(restored);

        expect(input.readOnly).toBe(false);
        expect(form.dataset.msSubmitted).toBeUndefined();
        input.value = "";
        type(input, "654321");
        expect(posts).toBe(2);
    });

    it("keeps the submission locked on a pageshow that is not a restore", async () => {
        const form = await mount(true);
        const input = form.elements["two-factor-authentication"];
        type(input, "123456");
        const fresh = new Event("pageshow");
        fresh.persisted = false;
        window.dispatchEvent(fresh);
        expect(input.readOnly).toBe(true);
        expect(form.dataset.msSubmitted).toBe("1");
    });

    it("does nothing on a page without the form", async () => {
        document.body.innerHTML = "<p>none</p>";
        vi.resetModules();
        await expect(import("./two-factor-login.js")).resolves.toBeDefined();
    });

    it("falls back to submit() where requestSubmit is missing, once", async () => {
        const form = await mount(true);
        const input = form.elements["two-factor-authentication"];
        form.requestSubmit = undefined;
        type(input, "123456");
        type(input, "123456");
        expect(posts).toBe(1);
        expect(form.dataset.msSubmitted).toBe("1");
    });

    it("leaves a page without the form alone", async () => {
        document.body.innerHTML = "<p>no form</p>";
        vi.resetModules();
        await expect(import("./two-factor-login.js")).resolves.toBeDefined();
    });

    it("leaves a form without the code field alone", async () => {
        document.body.innerHTML =
            '<form name="two-factor-authentication-form"></form>';
        vi.resetModules();
        await import("./two-factor-login.js");
        const form = document.forms["two-factor-authentication-form"];
        expect(form.dataset.msSubmitted).toBeUndefined();
    });
});
