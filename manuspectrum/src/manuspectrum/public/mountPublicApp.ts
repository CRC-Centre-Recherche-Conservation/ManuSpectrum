import { createVueApplication } from "@/arches_vue_components/application";
import { en } from "primelocale/js/en.js";
import { fr } from "primelocale/js/fr.js";

import { guardLocalStorage } from "@/manuspectrum/public/safe-storage.ts";
import { PUBLIC_THEME } from "@/manuspectrum/themes/public-theme.ts";

import type { App, Component } from "vue";
import type { PrimeVueLocaleOptions } from "primevue/config";

export interface MountPublicAppOptions {
    component: Component;
    mountPoint: Element;
    initialProps?: Record<string, unknown>;
}

/** PrimeVue's built-in strings (aria labels, close buttons) in the page language; English for any language the site does not offer. */
export function primeVueLocale(lang: string): PrimeVueLocaleOptions {
    return lang.toLowerCase().startsWith("fr") ? fr : en;
}

/**
 * Mount a public Vue page with the Arches application plugins and the public theme.
 *
 * Rejects when the application cannot start (i18n request, chunk load); the
 * page shim shows the server-rendered fallback. `aria-busy` is cleared only
 * once the component is mounted.
 */
export async function mountPublicApp({
    component,
    mountPoint,
    initialProps = {},
}: MountPublicAppOptions): Promise<App<Element>> {
    guardLocalStorage();
    const app = await createVueApplication({
        component,
        themeConfiguration: {
            ...PUBLIC_THEME,
            locale: primeVueLocale(document.documentElement.lang),
        },
        initialProps,
    });
    app.mount(mountPoint);
    mountPoint.setAttribute("aria-busy", "false");
    return app;
}
