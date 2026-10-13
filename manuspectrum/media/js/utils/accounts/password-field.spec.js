import { describe, it, expect, beforeEach } from "vitest";
import init, { strengthOf } from "./password-field";

const RULES = [
    ["length", "At least 12 characters"],
    ["upper", "Upper"],
    ["lower", "Lower"],
    ["digit", "Digit"],
    ["symbol", "Symbol"],
];

function markup(minLength = 12) {
    const items = RULES.map(
        ([rule, text]) =>
            `<li data-rule="${rule}" data-met="met" data-unmet="not met">${text} <span class="ms-pw-state"></span></li>`,
    ).join("");
    return `<form>
      <span data-ms-pw-wrap><input id="id_new_password1" type="password">
        <button type="button" class="ms-pw-toggle" hidden aria-pressed="false" aria-label="Show password" data-show="Show password" data-hide="Hide password"></button></span>
      <span data-ms-pw-meter hidden data-for="id_new_password1" data-min-length="${minLength}" data-symbols="!#$">
        <span data-ms-pw-word data-weak="Weak" data-fair="Fair" data-strong="Strong"></span><ul>${items}</ul></span>
      <span data-ms-pw-wrap><input id="id_new_password2" type="password">
        <button type="button" class="ms-pw-toggle" hidden aria-pressed="false" aria-label="Show password" data-show="Show password" data-hide="Hide password"></button></span>
      <span data-ms-pw-match data-for="id_new_password2" data-with="id_new_password1" data-match="Match" data-mismatch="No match"></span>
    </form>`;
}

function type(input, value) {
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
}

const $ = (sel) => document.querySelector(sel);

describe("password-field", () => {
    beforeEach(() => {
        document.body.innerHTML = markup();
    });

    it("reveals and flips the toggle, and re-masks on submit", () => {
        init(document);
        const button = $(".ms-pw-toggle");
        const input = $("#id_new_password1");
        expect(button.hidden).toBe(false);
        button.click();
        expect(input.type).toBe("text");
        expect(button.getAttribute("aria-pressed")).toBe("true");
        expect(button.getAttribute("aria-label")).toBe("Hide password");
        button.click();
        expect(input.type).toBe("password");
        button.click();
        $("form").dispatchEvent(new Event("submit", { cancelable: true }));
        expect(input.type).toBe("password");
        expect(button.getAttribute("aria-pressed")).toBe("false");
    });

    it("rates weak, fair and strong from the rules", () => {
        init(document);
        const input = $("#id_new_password1");
        const word = $("[data-ms-pw-word]");
        type(input, "abc");
        expect(word.textContent).toBe("Weak");
        type(input, "Abcdefghijk1");
        expect(word.textContent).toBe("Fair");
        type(input, "Abcdefghijk1!");
        expect(word.textContent).toBe("Strong");
        expect($('[data-rule="symbol"]').classList.contains("is-met")).toBe(
            true,
        );
        type(input, "");
        expect(word.textContent).toBe("");
    });

    it("reads the minimum length from the data attribute", () => {
        document.body.innerHTML = markup(20);
        init(document);
        type($("#id_new_password1"), "Abcdefghijk1!");
        expect($('[data-rule="length"]').classList.contains("is-met")).toBe(
            false,
        );
        expect($("[data-ms-pw-word]").textContent).toBe("Weak");
        type($("#id_new_password1"), "Abcdefghijklmnopqrs1!");
        expect($('[data-rule="length"]').classList.contains("is-met")).toBe(
            true,
        );
    });

    it("tells whether the two passwords match", () => {
        init(document);
        const line = $("[data-ms-pw-match]");
        type($("#id_new_password1"), "secret");
        expect(line.textContent).toBe("");
        type($("#id_new_password2"), "secre");
        expect(line.textContent).toBe("No match");
        type($("#id_new_password2"), "secret");
        expect(line.textContent).toBe("Match");
        type($("#id_new_password1"), "other");
        expect(line.textContent).toBe("No match");
    });

    it("destroy removes the listeners and hides the enhancement", () => {
        const destroy = init(document);
        const button = $(".ms-pw-toggle");
        button.click();
        destroy();
        expect($("#id_new_password1").type).toBe("password");
        expect(button.hidden).toBe(true);
        button.click();
        expect($("#id_new_password1").type).toBe("password");
        type($("#id_new_password1"), "Abcdefghijk1!");
        expect($("[data-ms-pw-word]").textContent).toBe("");
        type($("#id_new_password2"), "x");
        expect($("[data-ms-pw-match]").textContent).toBe("");
    });

    it("leaves a page without the markup untouched", () => {
        document.body.innerHTML = "<form><input type='password'></form>";
        const before = document.body.innerHTML;
        init(document)();
        expect(document.body.innerHTML).toBe(before);
    });

    it("strengthOf is empty for an empty value", () => {
        expect(strengthOf("", { length: false }).level).toBe("");
    });
});
