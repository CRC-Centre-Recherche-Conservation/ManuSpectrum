// Shared nav behaviours: glass-scroll header, mobile drawer disclosure state,
// and the About dropdown's click/keyboard/outside-click contract.

import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, beforeEach, vi } from "vitest";
import initMsNav, { MENU_OPEN_CLASS, NAV_JS_CLASS } from "./ms-nav";

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

    it("moves focus into the drawer on open", () => {
        boot();
        document.getElementById("ms-hamburger").click();
        expect(document.activeElement).toBe(
            document.querySelector("#ms-mobile-nav a"),
        );
    });

    it("Escape closes it and gives focus back to the menu button", () => {
        boot();
        const burger = document.getElementById("ms-hamburger");
        burger.click();
        document.activeElement.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        );
        expect(
            document.getElementById("ms-mobile-nav").classList.contains("open"),
        ).toBe(false);
        expect(burger.getAttribute("aria-expanded")).toBe("false");
        expect(document.activeElement).toBe(burger);
        expect(document.body.style.overflow).toBe("");
    });

    it("raises the header and places the drawer under it while open", () => {
        boot();
        const header = document.getElementById("ms-header");
        Object.defineProperty(header, "offsetHeight", {
            value: 72,
            configurable: true,
        });
        document.getElementById("ms-hamburger").click();
        expect(header.classList.contains(MENU_OPEN_CLASS)).toBe(true);
        expect(
            document
                .getElementById("ms-mobile-nav")
                .style.getPropertyValue("--ms-header-h"),
        ).toBe("72px");
        Object.defineProperty(header, "offsetHeight", {
            value: 57,
            configurable: true,
        });
        header.dispatchEvent(new Event("transitionend"));
        expect(
            document
                .getElementById("ms-mobile-nav")
                .style.getPropertyValue("--ms-header-h"),
        ).toBe("57px");
        document.getElementById("ms-hamburger").click();
        expect(header.classList.contains(MENU_OPEN_CLASS)).toBe(false);
    });

    it("closes and unlocks the page when a resize hides the menu button", () => {
        boot();
        const burger = document.getElementById("ms-hamburger");
        burger.click();
        burger.style.display = "none";
        window.dispatchEvent(new Event("resize"));
        expect(
            document.getElementById("ms-mobile-nav").classList.contains("open"),
        ).toBe(false);
        expect(document.body.style.overflow).toBe("");
    });

    it("re-places the open drawer on a resize that keeps the menu button", () => {
        boot();
        const header = document.getElementById("ms-header");
        const nav = document.getElementById("ms-mobile-nav");
        document.getElementById("ms-hamburger").click();
        Object.defineProperty(header, "offsetHeight", {
            value: 90,
            configurable: true,
        });
        window.dispatchEvent(new Event("resize"));
        expect(nav.classList.contains("open")).toBe(true);
        expect(nav.style.getPropertyValue("--ms-header-h")).toBe("90px");
    });

    it("ignores Escape, resizes and child transitions while closed", () => {
        boot();
        const header = document.getElementById("ms-header");
        const nav = document.getElementById("ms-mobile-nav");
        header.appendChild(document.createElement("span"));
        document.body.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        );
        window.dispatchEvent(new Event("resize"));
        header.firstChild.dispatchEvent(
            new Event("transitionend", { bubbles: true }),
        );
        expect(nav.classList.contains("open")).toBe(false);
        expect(nav.style.getPropertyValue("--ms-header-h")).toBe("");
        expect(document.body.style.overflow).toBe("");
    });

    it("works without a header", () => {
        document.body.innerHTML = NAV.replace(
            '<header id="ms-header"></header>',
            "",
        );
        window.matchMedia = vi.fn().mockReturnValue({ matches: false });
        initMsNav();
        const nav = document.getElementById("ms-mobile-nav");
        document.getElementById("ms-hamburger").click();
        expect(nav.classList.contains("open")).toBe(true);
        expect(nav.style.getPropertyValue("--ms-header-h")).toBe("");
        window.dispatchEvent(new Event("resize"));
        expect(nav.classList.contains("open")).toBe(true);
    });

    it("toggles the About group and exposes aria-expanded", () => {
        boot();
        const groupToggle = document.querySelector(
            ".ms-mobile-nav-group-toggle",
        );
        groupToggle.click();
        expect(
            document
                .getElementById("ms-mobile-about")
                .classList.contains("open"),
        ).toBe(true);
        expect(groupToggle.getAttribute("aria-expanded")).toBe("true");
        groupToggle.click();
        expect(groupToggle.getAttribute("aria-expanded")).toBe("false");
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

describe("CSS default hand-over", () => {
    it("marks the header with the class the stylesheet's hover/focus default is keyed on", () => {
        const scss = fs.readFileSync(
            path.join(
                path.dirname(new URL(import.meta.url).pathname),
                "../../css/_ms-chrome.scss",
            ),
            "utf-8",
        );
        expect(scss).toContain(
            `.ms-header:not(.${NAV_JS_CLASS}) .ms-nav-dropdown:hover`,
        );
        expect(scss).toContain(
            `.ms-header:not(.${NAV_JS_CLASS}) .ms-nav-dropdown:focus-within`,
        );

        document.body.innerHTML = NAV;
        const header = document.getElementById("ms-header");
        window.matchMedia = vi.fn().mockReturnValue({ matches: false });
        initMsNav();
        expect(header.classList.contains(NAV_JS_CLASS)).toBe(true);
    });
});
