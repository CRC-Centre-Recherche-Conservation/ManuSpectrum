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
    retry: () => void;
}

/**
 * Load a payload whenever its source string changes, aborting the previous load.
 *
 * `data` keeps the last payload while the next one loads, so a screen does not
 * flash empty. A 404 is `unavailable`; anything else is `error`, which a retry
 * reloads. Abort answers are dropped. The stored controller is cleared once a
 * request settles, so disposing the scope afterwards does not abort it again.
 * A payload `cached` returns for the source is taken as is, with no request;
 * Retry always loads.
 */
export function useRequest<T>(
    source: () => string | null,
    load: (argument: string, signal: AbortSignal) => Promise<T>,
    cached?: (argument: string) => T | null,
): RequestHandle<T> {
    const status = ref<RequestStatus>("idle");
    const data = shallowRef<T | null>(null);
    let controller: AbortController | null = null;

    async function run(
        argument: string | null,
        useCache = true,
    ): Promise<void> {
        controller?.abort();
        controller = null;
        if (argument === null) {
            status.value = "idle";
            data.value = null;
            return;
        }
        const kept = useCache ? cached?.(argument) ?? null : null;
        if (kept !== null) {
            data.value = kept;
            status.value = "ready";
            return;
        }
        const current = new AbortController();
        controller = current;
        status.value = "loading";
        try {
            const result = await load(argument, current.signal);
            if (controller === current) {
                data.value = result;
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

    watch(source, (argument) => void run(argument), { immediate: true });
    onScopeDispose(() => controller?.abort());

    return { status, data, retry: () => void run(source(), false) };
}
