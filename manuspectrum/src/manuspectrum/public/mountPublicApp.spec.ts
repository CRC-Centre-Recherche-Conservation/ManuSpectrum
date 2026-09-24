import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";

import { mountPublicApp } from "@/manuspectrum/public/mountPublicApp.ts";

const ORIGINAL = Object.getOwnPropertyDescriptor(window, "localStorage");
const I18N_ROUTE = "arches:get_frontend_i18n_data";

const Probe = defineComponent({
    props: { connected: { type: Boolean, default: false } },
    setup(props) {
        return () =>
            h(
                "p",
                { class: "probe" },
                props.connected ? "connected" : "visitor",
            );
    },
});

beforeEach(() => {
    document.documentElement.lang = "en";
    document.body.innerHTML = '<div id="app" aria-busy="true"></div>';
    vi.stubGlobal("ARCHES_URLS", {
        [I18N_ROUTE]: [
            {
                url: "/{language_code}/api/get_frontend_i18n_data",
                params: ["language_code"],
            },
        ],
    });
    vi.stubGlobal("matchMedia", () => ({ matches: false }));
    vi.stubGlobal(
        "fetch",
        vi.fn(async () => ({
            ok: true,
            status: 200,
            statusText: "OK",
            json: async () => ({
                enabled_languages: { en: "English" },
                language: "en",
                translations: { en: {} },
            }),
        })),
    );
});

afterEach(() => {
    vi.unstubAllGlobals();
    if (ORIGINAL) {
        Object.defineProperty(window, "localStorage", ORIGINAL);
    } else {
        Reflect.deleteProperty(window, "localStorage");
    }
});

describe("mountPublicApp", () => {
    it("mounts the component with its initial props and clears aria-busy", async () => {
        const mountPoint = document.getElementById("app") as HTMLElement;
        const app = await mountPublicApp({
            component: Probe,
            mountPoint,
            initialProps: { connected: true },
        });
        expect(mountPoint.querySelector(".probe")?.textContent).toBe(
            "connected",
        );
        expect(mountPoint.getAttribute("aria-busy")).toBe("false");
        app.unmount();
    });

    it("boots the application when localStorage access throws", async () => {
        Object.defineProperty(window, "localStorage", {
            configurable: true,
            get() {
                throw new DOMException("blocked", "SecurityError");
            },
        });
        const mountPoint = document.getElementById("app") as HTMLElement;
        const app = await mountPublicApp({ component: Probe, mountPoint });
        expect(mountPoint.querySelector(".probe")?.textContent).toBe("visitor");
        app.unmount();
    });

    it("rejects and leaves the mount point busy when the i18n request fails", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => ({
                ok: false,
                status: 503,
                statusText: "Service Unavailable",
            })),
        );
        const mountPoint = document.getElementById("app") as HTMLElement;
        await expect(
            mountPublicApp({ component: Probe, mountPoint }),
        ).rejects.toThrow();
        expect(mountPoint.getAttribute("aria-busy")).toBe("true");
    });
});
