import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    IMAGE_RETRY_AFTER_MS,
    hasImageFailed,
    markImageFailed,
} from "@/manuspectrum/pages/AnalysisExplorer/failed-images.ts";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("failed images", () => {
    it("holds a failed image back for a while, then lets it be asked again", () => {
        const url = "https://iiif.example/failed-once.jpg";
        markImageFailed(url);
        expect(hasImageFailed(url)).toBe(true);

        vi.advanceTimersByTime(IMAGE_RETRY_AFTER_MS - 1);
        expect(hasImageFailed(url)).toBe(true);

        vi.advanceTimersByTime(1);
        expect(hasImageFailed(url)).toBe(false);
        expect(hasImageFailed("https://iiif.example/other.jpg")).toBe(false);
    });
});
