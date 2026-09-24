import { definePreset, palette } from "@primeuix/themes";

import { ArchesPreset } from "@/arches_vue_components/themes/default.ts";

import type { ArchesThemeConfiguration } from "@/arches_vue_components/themes";

// The one place where public pages give PrimeVue raw colours: the values of
// --ink and --blue-text in _ms-chrome.scss (public-theme.spec.ts pins --ink).
export const PUBLIC_INK = "#1a1a2e";
const PUBLIC_FOCUS = "#1d4ed8";
const OVERLAY_Z_INDEX = 1100;
const TOOLTIP_Z_INDEX = 1200;

export const PublicPreset = definePreset(ArchesPreset, {
    semantic: {
        primary: palette(PUBLIC_INK),
        focusRing: {
            width: "0.125rem",
            style: "solid",
            color: PUBLIC_FOCUS,
            offset: "0.125rem",
        },
        colorScheme: {
            light: {
                primary: {
                    color: PUBLIC_INK,
                    contrastColor: "#ffffff",
                    hoverColor: "{primary.800}",
                    activeColor: "{primary.900}",
                },
                highlight: {
                    background: "{primary.50}",
                    focusBackground: "{primary.100}",
                    color: PUBLIC_INK,
                    focusColor: PUBLIC_INK,
                },
            },
        },
    },
});

export const PUBLIC_THEME: ArchesThemeConfiguration = {
    theme: {
        preset: PublicPreset,
        options: {
            prefix: "p",
            // createVueApplication strips the first character and adds the rest
            // as a class on <html> when the OS prefers dark: "none" yields an
            // inert class "one".
            darkModeSelector: "none",
            // The public chrome's reset is unlayered; layered PrimeVue rules
            // would lose to it at any specificity.
            cssLayer: false,
        },
    },
    zIndex: {
        modal: OVERLAY_Z_INDEX,
        overlay: OVERLAY_Z_INDEX,
        menu: OVERLAY_Z_INDEX,
        tooltip: TOOLTIP_Z_INDEX,
    },
};
