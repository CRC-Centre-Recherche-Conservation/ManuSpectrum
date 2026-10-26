import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, nextTick, reactive } from "vue";
import { mount } from "@vue/test-utils";

import {
    rewriteHeaderLinks,
    useUrlState,
} from "@/manuspectrum/public/useUrlState.ts";

import type {
    HistoryMode,
    UrlStateBinding,
} from "@/manuspectrum/public/useUrlState.ts";

interface DemoState {
    screen: string;
    q: string;
}

function makeBinding(
    state: DemoState,
    mode: HistoryMode = "replace",
): UrlStateBinding<DemoState> {
    return {
        snapshot: () => ({ screen: state.screen, q: state.q }),
        toQuery: (snapshot) => {
            const query = new URLSearchParams();
            if (snapshot.screen !== "home")
                query.set("screen", snapshot.screen);
            if (snapshot.q) query.set("q", snapshot.q);
            return query;
        },
        apply: (query) => {
            state.screen = query.get("screen") ?? "home";
            state.q = query.get("q") ?? "";
        },
        historyMode: (previous, next) =>
            previous.screen !== next.screen ? "push" : mode,
    };
}

function mountWith(binding: UrlStateBinding<DemoState>) {
    return mount(
        defineComponent({
            setup() {
                useUrlState(binding);
                return () => h("div");
            },
        }),
    );
}

beforeEach(() => {
    window.history.replaceState(null, "", "/en/discover");
    document.body.innerHTML = `
        <header id="ms-header">
            <a class="ms-btn-signin" href="/en/auth/?next=/en/">Sign in</a>
            <a href="/en/auth/?next=/en/&amp;logout=true">Sign out</a>
            <nav class="ms-lang-switch"><a hreflang="fr" href="http://localhost:3000/fr/discover">FR</a></nav>
        </header>
        <div id="ms-mobile-nav"><a href="/en/auth/?next=/en/">Sign in</a></div>`;
});

afterEach(() => {
    vi.restoreAllMocks();
});

describe("useUrlState", () => {
    it("adopts the location on start and rewrites it canonically", () => {
        window.history.replaceState(null, "", "/en/discover?q=XRF&unknown=1");
        const state = reactive({ screen: "home", q: "" });
        const replace = vi.spyOn(window.history, "replaceState");
        mountWith(makeBinding(state));
        expect(state.q).toBe("XRF");
        expect(replace).toHaveBeenCalledWith(null, "", "/en/discover?q=XRF");
    });

    it("pushes or replaces according to the binding", async () => {
        const state = reactive({ screen: "home", q: "" });
        mountWith(makeBinding(state));
        const push = vi.spyOn(window.history, "pushState");
        const replace = vi.spyOn(window.history, "replaceState");
        state.q = "lead";
        await nextTick();
        expect(replace).toHaveBeenLastCalledWith(
            null,
            "",
            "/en/discover?q=lead",
        );
        state.screen = "results";
        await nextTick();
        expect(push).toHaveBeenLastCalledWith(
            null,
            "",
            "/en/discover?screen=results&q=lead",
        );
    });

    it("writes nothing when the binding answers none", async () => {
        const state = reactive({ screen: "home", q: "" });
        mountWith(makeBinding(state, "none"));
        const push = vi.spyOn(window.history, "pushState");
        const replace = vi.spyOn(window.history, "replaceState");
        state.q = "lead";
        await nextTick();
        expect(push).not.toHaveBeenCalled();
        expect(replace).not.toHaveBeenCalled();
    });

    it("applies the location on popstate without writing history", async () => {
        const state = reactive({ screen: "home", q: "" });
        mountWith(makeBinding(state));
        window.history.pushState(
            null,
            "",
            "/en/discover?screen=results&q=gold",
        );
        const push = vi.spyOn(window.history, "pushState");
        window.dispatchEvent(new PopStateEvent("popstate"));
        await nextTick();
        expect(state).toEqual({ screen: "results", q: "gold" });
        expect(push).not.toHaveBeenCalled();
    });

    it("stops listening to popstate once unmounted", () => {
        const state = reactive({ screen: "home", q: "" });
        const wrapper = mountWith(makeBinding(state));
        wrapper.unmount();
        window.history.pushState(null, "", "/en/discover?q=gold");
        window.dispatchEvent(new PopStateEvent("popstate"));
        expect(state.q).toBe("");
    });
});

describe("rewriteHeaderLinks", () => {
    it("rewrites the language links and the next= links with the current query", () => {
        rewriteHeaderLinks({ pathname: "/en/discover", search: "?q=XRF" });
        const french =
            document.querySelector<HTMLAnchorElement>(".ms-lang-switch a")!;
        expect(french.getAttribute("href")).toBe(
            "http://localhost:3000/fr/discover?q=XRF",
        );
        const [signIn, signOut] = document.querySelectorAll<HTMLAnchorElement>(
            "#ms-header a[href*='next=']",
        );
        expect(new URL(signIn.href).searchParams.get("next")).toBe(
            "/en/discover?q=XRF",
        );
        expect(new URL(signOut.href).searchParams.get("logout")).toBe("true");
        expect(new URL(signOut.href).searchParams.get("next")).toBe(
            "/en/discover?q=XRF",
        );
        const mobile =
            document.querySelector<HTMLAnchorElement>("#ms-mobile-nav a")!;
        expect(mobile.getAttribute("href")).toBe(
            "/en/auth/?next=%2Fen%2Fdiscover%3Fq%3DXRF",
        );
    });

    it("keeps the language link host from the server", () => {
        rewriteHeaderLinks({ pathname: "//evil.example/x", search: "?q=1" });
        const french =
            document.querySelector<HTMLAnchorElement>(".ms-lang-switch a")!;
        expect(new URL(french.href).host).toBe("localhost:3000");
        const signIn =
            document.querySelector<HTMLAnchorElement>(".ms-btn-signin")!;
        expect(signIn.getAttribute("href")?.startsWith("/en/auth/")).toBe(true);
        expect(new URL(signIn.href).searchParams.get("next")).toBe("/");
    });

    it("clears the language link query when the page has none", () => {
        rewriteHeaderLinks({ pathname: "/en/discover", search: "?q=1" });
        rewriteHeaderLinks({ pathname: "/en/discover", search: "" });
        const french =
            document.querySelector<HTMLAnchorElement>(".ms-lang-switch a")!;
        expect(french.getAttribute("href")).toBe(
            "http://localhost:3000/fr/discover",
        );
    });
});
