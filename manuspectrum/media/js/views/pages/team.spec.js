// team.js has one behaviour worth pinning: a broken portrait must flip its
// card to the icon fallback instead of showing the browser's broken-image glyph.

import { describe, it, expect, vi } from "vitest";

vi.mock("utils/ms-nav", () => ({ default: () => {} }));

async function boot() {
    document.body.innerHTML = `
        <div class="ms-member-photo" id="p1">
            <img class="ms-member-img" src="/img/team/team-01.jpg">
        </div>
        <section class="reveal"></section>`;
    globalThis.IntersectionObserver = class {
        observe() {}
        unobserve() {}
        disconnect() {}
    };
    vi.resetModules();
    await import("./team");
    document.dispatchEvent(new Event("DOMContentLoaded"));
}

describe("portrait fallback", () => {
    it("marks the photo box when the image errors", async () => {
        await boot();
        document
            .querySelector(".ms-member-img")
            .dispatchEvent(new Event("error"));
        expect(
            document.getElementById("p1").classList.contains("is-fallback"),
        ).toBe(true);
    });

    it("does not mark healthy photos", async () => {
        await boot();
        expect(
            document.getElementById("p1").classList.contains("is-fallback"),
        ).toBe(false);
    });
});
