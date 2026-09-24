import { createVueApplication } from "@/arches_vue_components/application";

import { guardLocalStorage } from "@/manuspectrum/public/safe-storage.ts";
import { PUBLIC_THEME } from "@/manuspectrum/themes/public-theme.ts";

import type { App, Component } from "vue";

export interface MountPublicAppOptions {
    component: Component;
    mountPoint: Element;
    initialProps?: Record<string, unknown>;
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
        themeConfiguration: PUBLIC_THEME,
        initialProps,
    });
    app.mount(mountPoint);
    mountPoint.setAttribute("aria-busy", "false");
    return app;
}
