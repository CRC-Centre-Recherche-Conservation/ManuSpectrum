import { inject, onBeforeUnmount, onMounted, watch } from "vue";

import { WINDOW_RESIZE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

import type { Ref } from "vue";
import type L from "leaflet";

/**
 * Keeps a Leaflet map the size of its container: when the window changes
 * size (`WINDOW_RESIZE_KEY`) or the container itself does (the gallery
 * opening, another layout), the map reads its size again and, when the
 * reader had not moved the view (`keepsFit`), fits the image again in it.
 * Leaflet only follows the browser window by itself.
 */
export function useMapResize(options: {
    host: Readonly<Ref<HTMLElement | null>>;
    map: () => L.Map | null;
    /** Whether the view is still the fit of the image, or nothing is fitted yet. */
    keepsFit: () => boolean;
    refit: () => void;
}): void {
    const resized = inject(WINDOW_RESIZE_KEY, null);
    let observer: ResizeObserver | null = null;
    let frame: number | null = null;

    function update(): void {
        frame = null;
        const map = options.map();
        if (!map) return;
        const held = options.keepsFit();
        map.invalidateSize();
        if (held) options.refit();
    }

    function schedule(): void {
        if (frame === null) frame = requestAnimationFrame(update);
    }

    watch(() => resized?.value, update);

    onMounted(() => {
        if (typeof ResizeObserver === "undefined" || !options.host.value)
            return;
        observer = new ResizeObserver(schedule);
        observer.observe(options.host.value);
    });

    onBeforeUnmount(() => {
        observer?.disconnect();
        observer = null;
        if (frame !== null) cancelAnimationFrame(frame);
        frame = null;
    });
}
