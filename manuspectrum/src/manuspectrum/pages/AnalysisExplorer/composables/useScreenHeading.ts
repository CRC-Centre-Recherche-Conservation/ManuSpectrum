import { inject, watch } from "vue";

import { SCREEN_FOCUS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

/**
 * Focus the element `target` returns once it is rendered, when the shell has
 * asked for the screen heading to take the focus (`SCREEN_FOCUS_KEY`). The
 * element carries `tabindex="-1"`. A screen whose heading renders later (after
 * a load) takes the focus then; the request is cleared by the first heading
 * that takes it.
 */
export function useScreenHeading(target: () => HTMLElement | null): void {
    const pending = inject(SCREEN_FOCUS_KEY, null);
    watch(
        () => [target(), pending?.value ?? false] as const,
        ([element, isPending]) => {
            if (element && isPending && pending) {
                pending.value = false;
                element.focus();
            }
        },
        { flush: "post", immediate: true },
    );
}
