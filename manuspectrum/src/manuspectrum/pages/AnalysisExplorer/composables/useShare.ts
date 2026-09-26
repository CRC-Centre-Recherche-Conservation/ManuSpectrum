import { toValue } from "vue";

import {
    getJson,
    peekJson,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import { shareQuery } from "@/manuspectrum/pages/AnalysisExplorer/share/scope.ts";

import type { MaybeRefOrGetter } from "vue";

import type { SharePayload } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import type { OfferedScope } from "@/manuspectrum/pages/AnalysisExplorer/share/scope.ts";

export const SHARE_ROUTE = "manuspectrum:explorer-share";

/** What « Share and export » offers for `scope`, with the restricted-access items when `restricted`; no request without a scope. */
export function useShare(
    scope: MaybeRefOrGetter<OfferedScope | null>,
    restricted: MaybeRefOrGetter<boolean>,
): RequestHandle<SharePayload> {
    return useRequest(
        () => {
            const current = toValue(scope);
            return current
                ? shareQuery(current, toValue(restricted)).toString()
                : null;
        },
        (query, signal, reload) =>
            getJson<SharePayload>(SHARE_ROUTE, {
                query: new URLSearchParams(query),
                signal,
                reload,
            }),
        {
            cached: (query) =>
                peekJson<SharePayload>(SHARE_ROUTE, {
                    query: new URLSearchParams(query),
                }),
        },
    );
}
