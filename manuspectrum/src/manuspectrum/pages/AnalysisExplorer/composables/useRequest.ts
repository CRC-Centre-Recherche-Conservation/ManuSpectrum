import { onScopeDispose, ref, shallowRef, watch } from "vue";

import { UnavailableError } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";

import type { Ref, ShallowRef } from "vue";

export type RequestStatus =
    | "idle"
    | "loading"
    | "ready"
    | "unavailable"
    | "error";

export interface RequestHandle<T> {
    status: Ref<RequestStatus>;
    data: ShallowRef<T | null>;
    /** The source string `data` answers. */
    loaded: Ref<string | null>;
    retry: () => void;
}

export interface RequestOptions<T> {
    /** A payload already held for the source, taken as is with no request and no wait. */
    cached?: (argument: string) => T | null;
    /** Whether a change from `previous` to `next` waits `DEBOUNCE_MS` for the source to settle. */
    debounce?: (next: string, previous: string) => boolean;
}

/** How long a debounced source must stay unchanged before its request starts. */
export const DEBOUNCE_MS = 300;

/**
 * Load a payload whenever its source string changes, aborting the previous load.
 *
 * `data` keeps the last payload while the next one loads, so a screen does not
 * flash empty. A 404 is `unavailable`; anything else is `error`, which a retry
 * reloads (`reload` true, the tab memo bypassed). Abort answers are dropped.
 * The stored controller is cleared once a request settles, so disposing the
 * scope afterwards does not abort it again. A payload `cached` returns for the
 * source is taken at once. A change `debounce` accepts shows `loading` at once
 * and starts its request once the source has not changed for `DEBOUNCE_MS`;
 * the first load and a retry start at once.
 */
export function useRequest<T>(
    source: () => string | null,
    load: (
        argument: string,
        signal: AbortSignal,
        reload: boolean,
    ) => Promise<T>,
    { cached, debounce }: RequestOptions<T> = {},
): RequestHandle<T> {
    const status = ref<RequestStatus>("idle");
    const data = shallowRef<T | null>(null);
    const loaded = ref<string | null>(null);
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    function stop(): void {
        if (timer !== null) clearTimeout(timer);
        timer = null;
        controller?.abort();
        controller = null;
    }

    function run(
        argument: string | null,
        previous: string | null | undefined,
        reload = false,
    ): void {
        stop();
        if (argument === null) {
            status.value = "idle";
            data.value = null;
            loaded.value = null;
            return;
        }
        const kept = reload ? null : cached?.(argument) ?? null;
        if (kept !== null) {
            data.value = kept;
            loaded.value = argument;
            status.value = "ready";
            return;
        }
        status.value = "loading";
        if (!reload && previous != null && debounce?.(argument, previous)) {
            timer = setTimeout(() => {
                timer = null;
                void fetchNow(argument, false);
            }, DEBOUNCE_MS);
            return;
        }
        void fetchNow(argument, reload);
    }

    async function fetchNow(argument: string, reload: boolean): Promise<void> {
        const current = new AbortController();
        controller = current;
        status.value = "loading";
        try {
            const result = await load(argument, current.signal, reload);
            if (controller === current) {
                data.value = result;
                loaded.value = argument;
                status.value = "ready";
            }
        } catch (error) {
            if (controller === current && !current.signal.aborted) {
                status.value =
                    error instanceof UnavailableError ? "unavailable" : "error";
            }
        } finally {
            if (controller === current) {
                controller = null;
            }
        }
    }

    watch(source, (argument, previous) => run(argument, previous), {
        immediate: true,
    });
    onScopeDispose(stop);

    return {
        status,
        data,
        loaded,
        retry: () => run(source(), null, true),
    };
}
