import {
    getSynthesis,
    peekSynthesis,
} from "@/manuspectrum/pages/AnalysisExplorer/api/synthesis.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { SynthesisResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

/** What the synthesis of `keys` is read for: each key once, sorted, comma-joined; null for no key. */
export function synthesisSource(keys: readonly string[]): string | null {
    return keys.length > 0 ? [...new Set(keys)].sort().join(",") : null;
}

/**
 * The synthesis `handle` holds when it answers for `keys` (read, and read
 * for those keys); null otherwise, while the next one is read or after a
 * failure included, when `handle` still holds the previous one.
 */
export function synthesisFor(
    handle: RequestHandle<SynthesisResponse>,
    keys: readonly string[],
): SynthesisResponse | null {
    const source = synthesisSource(keys);
    return source !== null &&
        handle.status.value === "ready" &&
        handle.loaded.value === source
        ? handle.data.value
        : null;
}

/**
 * The synthesis of the Selection's keys (D60) through the tab's memo: one
 * request per set of keys whatever their order, the previous one aborted
 * when the Selection changes before its answer; no request for an empty
 * Selection.
 */
export function useSynthesis(
    keys: () => readonly string[] | null,
): RequestHandle<SynthesisResponse> {
    return useRequest(
        () => synthesisSource(keys() ?? []),
        (ids, signal, reload) =>
            getSynthesis(ids.split(","), { signal, reload }),
        { cached: (ids) => peekSynthesis(ids.split(",")) },
    );
}
