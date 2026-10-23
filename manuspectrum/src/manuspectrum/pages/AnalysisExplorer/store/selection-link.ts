import {
    BASKET_LIMIT,
    uniqueKeys,
} from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";

import type { ItemKey } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export const SELECTION_PARAM = "sel";
const MAX_LENGTH = 4096;

export interface SharedSelection {
    keys: ItemKey[];
    truncated: number;
    invalid: number;
}

/** Keys of a shared `sel=` parameter: valid, unique, sorted, at most 30; null when none is valid. */
export function parseSelection(raw: string | null): SharedSelection | null {
    if (!raw) {
        return null;
    }
    const parts = raw
        .slice(0, MAX_LENGTH)
        .split(",")
        .map((part) => part.trim())
        .filter(Boolean);
    const { keys, invalid } = uniqueKeys(parts);
    if (keys.length === 0) {
        return null;
    }
    keys.sort();
    return {
        keys: keys.slice(0, BASKET_LIMIT),
        truncated: Math.max(0, keys.length - BASKET_LIMIT),
        invalid,
    };
}
