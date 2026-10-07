import { computed, inject, onScopeDispose, provide, shallowRef } from "vue";

import { WINDOW_ACTIONS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

import type { ComputedRef } from "vue";

import type { IconName } from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";

/** An action a window body offers in its window's header, as an icon button. */
export interface WindowAction {
    /** Stable within the window; the button's `data-action`. */
    id: string;
    icon: IconName;
    /** The button's name and tooltip. */
    label: string;
    /** Shown under the label in the tooltip; the button's description. */
    description?: string;
    /** A toggle's state; absent for a plain button. */
    pressed?: boolean;
    disabled?: boolean;
    run: () => void;
}

type ActionSource = () => readonly WindowAction[];

export interface WindowActionsHost {
    /** Adds a body's actions; the function returned takes them away. */
    register: (source: ActionSource) => () => void;
}

/**
 * Declares the actions of a window body, read again whenever what `source`
 * reads changes, and taken away when the body's scope ends. Outside a
 * window that hosts actions (`provideWindowActions`) nothing is shown.
 */
export function useWindowActions(source: ActionSource): void {
    const host = inject(WINDOW_ACTIONS_KEY, null);
    if (!host) return;
    onScopeDispose(host.register(source));
}

/** Hosts the actions its descendants declare, in the order they declared them. */
export function provideWindowActions(): ComputedRef<WindowAction[]> {
    const sources = shallowRef<readonly ActionSource[]>([]);
    provide(WINDOW_ACTIONS_KEY, {
        register(source: ActionSource): () => void {
            sources.value = [...sources.value, source];
            return () => {
                sources.value = sources.value.filter(
                    (entry) => entry !== source,
                );
            };
        },
    });
    return computed(() => sources.value.flatMap((source) => [...source()]));
}
