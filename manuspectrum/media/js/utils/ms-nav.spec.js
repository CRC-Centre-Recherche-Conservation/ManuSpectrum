// Shared nav behaviours: glass-scroll header, mobile drawer disclosure state,
// and the About dropdown's click/keyboard/outside-click contract.

import { describe, it, expect, beforeEach, vi } from "vitest";
import initMsNav from "./ms-nav";

const NAV = `
<header id="ms-header"></header>
<button id="ms-hamburger" aria-expanded="false"></button>
<div id="ms-mobile-nav">
    <a href="/x">link</a>
    <button class="ms-mobile-nav-group-toggle" aria-expanded="false"></button>
    <div id="ms-mobile-about"></div>
</div>
<li class="ms-nav-dropdown" id="ms-about-dropdown">
    <button class="ms-nav-dropdown-toggle" aria-expanded="false"></button>
    <div class="ms-nav-dropdown-menu"><ul>
        <li><a href="/a" id="dd-a">A</a></li>
        <li><a href="/b" id="dd-b">B</a></li>
    </ul></div>
</li>
<button id="outside"></button>`;

function boot({ hoverCapable = false } = {}) {
    document.body.innerHTML = NAV;
    window.matchMedia = vi.fn().mockReturnValue({ matches: hoverCapable });
    initMsNav();
}

const dd = () => document.getElementById("ms-about-dropdown");
const toggle = () => document.querySelector(".ms-nav-dropdown-toggle");

beforeEach(() => vi.restoreAllMocks());

describe("mobile drawer", () => {
    it("toggles open state and exposes aria-expanded", () => {
        boot();
        const burger = document.getElementById("ms-hamburger");
        burger.click();
        expect(
            document.getElementById("ms-mobile-nav").classList.contains("open"),
        ).toBe(true);
        expect(burger.getAttribute("aria-expanded")).toBe("true");
        burger.click();
        expect(burger.getAttribute("aria-expanded")).toBe("false");
    });

    it("closes when a drawer link is followed", () => {
        boot();
        document.getElementById("ms-hamburger").click();
        document.querySelector("#ms-mobile-nav a").click();
        expect(
            document.getElementById("ms-mobile-nav").classList.contains("open"),
        ).toBe(false);
    });
});

describe("About dropdown (touch / no-hover)", () => {
    it("click toggles open and closed", () => {
        boot({ hoverCapable: false });
        toggle().click();
        expect(dd().classList.contains("open")).toBe(true);
        expect(toggle().getAttribute("aria-expanded")).toBe("true");
        toggle().click();
        expect(dd().classList.contains("open")).toBe(false);
    });

    it("outside click closes it", () => {
        boot({ hoverCapable: false });
        toggle().click();
        document.getElementById("outside").click();
        expect(dd().classList.contains("open")).toBe(false);
    });

    it("Escape closes and refocuses the toggle", () => {
        boot({ hoverCapable: false });
        toggle().click();
        dd().dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        );
        expect(dd().classList.contains("open")).toBe(false);
        expect(document.activeElement).toBe(toggle());
    });

    it("arrow keys move focus through the links, wrapping", () => {
        boot({ hoverCapable: false });
        toggle().click();
        const menu = document.querySelector(".ms-nav-dropdown-menu");
        const down = () =>
            menu.dispatchEvent(
                new KeyboardEvent("keydown", {
                    key: "ArrowDown",
                    bubbles: true,
                }),
            );
        down();
        expect(document.activeElement.id).toBe("dd-a");
        down();
        expect(document.activeElement.id).toBe("dd-b");
        down(); // wraps
        expect(document.activeElement.id).toBe("dd-a");
        menu.dispatchEvent(
            new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true }),
        );
        expect(document.activeElement.id).toBe("dd-b");
    });
});

describe("mouse (hover-capable) click contract", () => {
    it("a mouse click only ever opens — hover-out closes", () => {
        boot({ hoverCapable: true });
        // mouse clicks carry detail >= 1; jsdom's .click() has detail 0, so
        // dispatch an explicit MouseEvent to simulate a real pointer click.
        const mouseClick = () =>
            toggle().dispatchEvent(
                new MouseEvent("click", { bubbles: true, detail: 1 }),
            );
        mouseClick();
        expect(dd().classList.contains("open")).toBe(true);
        mouseClick(); // must NOT toggle shut
        expect(dd().classList.contains("open")).toBe(true);
        dd().dispatchEvent(new MouseEvent("mouseleave"));
        expect(dd().classList.contains("open")).toBe(false);
    });

    it("a keyboard-synthesised click (detail 0) still toggles", () => {
        boot({ hoverCapable: true });
        toggle().click();
        expect(dd().classList.contains("open")).toBe(true);
        toggle().click();
        expect(dd().classList.contains("open")).toBe(false);
    });
});

describe("glass-scroll header", () => {
    it("adds .scrolled past 80px and removes it back at top", () => {
        boot();
        const header = document.getElementById("ms-header");
        Object.defineProperty(window, "scrollY", {
            value: 200,
            configurable: true,
        });
        window.dispatchEvent(new Event("scroll"));
        expect(header.classList.contains("scrolled")).toBe(true);
        Object.defineProperty(window, "scrollY", {
            value: 0,
            configurable: true,
        });
        window.dispatchEvent(new Event("scroll"));
        expect(header.classList.contains("scrolled")).toBe(false);
    });
});
