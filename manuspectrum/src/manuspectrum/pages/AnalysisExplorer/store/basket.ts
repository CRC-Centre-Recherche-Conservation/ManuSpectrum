import { validate as isUuid } from "uuid";

import type {
    BasketItem,
    BasketKind,
    ItemKey,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export const BASKET_LIMIT = 30;

const PAGE = /^\d{1,4}$/;
const KEY_SHAPE = /^(af|im|ch):([^:]+):([^:]+)$/;
const KIND_BY_PREFIX: Record<string, BasketKind> = {
    af: "analysis-file",
    im: "imaging",
    ch: "characterization",
};

/** Whether the second segment matches its kind: a file id for `af`, a page number for `im`, the literal `-` for `ch`. */
function hasValidSecondSegment(kind: string, second: string): boolean {
    if (kind === "af") return isUuid(second);
    if (kind === "im") return PAGE.test(second);
    return second === "-";
}

export function normalizeItemKey(raw: string): ItemKey | null {
    const key = raw.trim().toLowerCase();
    const match = KEY_SHAPE.exec(key);
    if (!match) {
        return null;
    }
    const [, kind, id, second] = match;
    if (!isUuid(id) || !hasValidSecondSegment(kind, second)) {
        return null;
    }
    return key as ItemKey;
}

export function kindOf(key: ItemKey): BasketKind {
    return KIND_BY_PREFIX[key.slice(0, 2)];
}

export function uniqueKeys(keys: readonly string[]): {
    keys: ItemKey[];
    invalid: number;
} {
    const unique: ItemKey[] = [];
    let invalid = 0;
    for (const raw of keys) {
        const key = normalizeItemKey(raw);
        if (key === null) {
            invalid += 1;
        } else if (!unique.includes(key)) {
            unique.push(key);
        }
    }
    return { keys: unique, invalid };
}

export function freeSlots(
    items: readonly BasketItem[],
    count: number,
): number[] {
    const taken = new Set(items.map((item) => item.slot));
    const slots: number[] = [];
    for (let slot = 0; slot < BASKET_LIMIT && slots.length < count; slot += 1) {
        if (!taken.has(slot)) {
            slots.push(slot);
        }
    }
    return slots;
}

export function slotLabel(slot: number): string {
    return `A${slot + 1}`;
}
