import {
    getSynthesis,
    peekSynthesis,
} from "@/manuspectrum/pages/AnalysisExplorer/api/synthesis.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { SynthesisResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

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
        () => {
            const current = keys();
            return current && current.length > 0
                ? [...new Set(current)].sort().join(",")
                : null;
        },
        (ids, signal, reload) =>
            getSynthesis(ids.split(","), { signal, reload }),
        { cached: (ids) => peekSynthesis(ids.split(",")) },
    );
}
