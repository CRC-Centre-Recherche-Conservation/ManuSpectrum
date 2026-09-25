import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

import { prefetchJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    INTENT_MS,
    useDocumentPrefetch,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocumentPrefetch.ts";

vi.mock("@/manuspectrum/pages/AnalysisExplorer/api/http.ts", () => ({
    prefetchJson: vi.fn(),
}));

beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(prefetchJson).mockReset();
});

afterEach(() => vi.useRealTimers());

describe("useDocumentPrefetch", () => {
    it("loads the document and its match once the reader rests on the card", () => {
        const scope = effectScope();
        const prefetch = scope.run(() =>
            useDocumentPrefetch(() => new URLSearchParams("technique=t1")),
        )!;
        prefetch.intend("doc-1");
        vi.advanceTimersByTime(INTENT_MS - 1);
        expect(prefetchJson).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(prefetchJson).toHaveBeenCalledWith(
            "manuspectrum:explorer-document",
            { urlParameters: { resourceid: "doc-1" } },
        );
        expect(prefetchJson).toHaveBeenCalledWith(
            "manuspectrum:explorer-document-match",
            {
                urlParameters: { resourceid: "doc-1" },
                query: new URLSearchParams("technique=t1"),
            },
        );
        scope.stop();
    });

    it("loads nothing for a card only passed over, or once the screen is gone", () => {
        const scope = effectScope();
        const prefetch = scope.run(() =>
            useDocumentPrefetch(() => new URLSearchParams()),
        )!;
        prefetch.intend("doc-1");
        vi.advanceTimersByTime(INTENT_MS - 1);
        prefetch.drop();
        prefetch.intend("doc-2");
        scope.stop();
        vi.advanceTimersByTime(INTENT_MS);
        expect(prefetchJson).not.toHaveBeenCalled();
    });
});
