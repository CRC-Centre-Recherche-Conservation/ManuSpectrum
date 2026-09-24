import type {
    BasketItem,
    BasketKind,
    ItemKey,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export const BASKET_LIMIT = 30;

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const ITEM_KEY = new RegExp(
    `^(?:af:${UUID}:${UUID}|im:${UUID}:\\d{1,4}|ch:${UUID}:-)$`,
);
const KIND_BY_PREFIX: Record<string, BasketKind> = {
    af: "analysis-file",
    im: "imaging",
    ch: "characterization",
};

export function normalizeItemKey(raw: string): ItemKey | null {
    const key = raw.trim().toLowerCase();
    return ITEM_KEY.test(key) ? key : null;
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
