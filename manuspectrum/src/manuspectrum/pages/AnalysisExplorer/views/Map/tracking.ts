import {
    FOCUS_MAX,
    nextFreeSlot,
    pinInSlots,
    pinnedOf,
    unpinFromSlots,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";

import type { FocusMode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";

/** At most as many followed materials as Compare's focus has slots (`--focus-1…4`). */
export const TRACK_MAX = FOCUS_MAX;
/** A hole in the address (`track=a&track=-&track=b`). */
export const TRACK_HOLE = "-";
const MAX_URI = 2048;

export type TrackResult = "pinned" | "unpinned" | "refused";

export interface TrackedMaterial {
    uri: string;
    slot: number;
}

export function trackedOf(
    slots: readonly (string | null)[],
): TrackedMaterial[] {
    return pinnedOf(slots).map(({ id, slot }) => ({ uri: id, slot }));
}

export function slotOf(
    slots: readonly (string | null)[],
    uri: string,
): number | null {
    const index = slots.indexOf(uri);
    return index < 0 ? null : index + 1;
}

/** Follows `uri` in the lowest hole, or stops following it (a hole stays); a fifth is refused and changes nothing. */
export function toggleTracked(
    slots: readonly (string | null)[],
    uri: string,
): { slots: (string | null)[]; result: TrackResult } {
    if (slots.includes(uri)) {
        return {
            slots: unpinFromSlots(slots, (id) => id === uri),
            result: "unpinned",
        };
    }
    if (nextFreeSlot(slots) === null) {
        return { slots: [...slots], result: "refused" };
    }
    return { slots: pinInSlots(slots, uri), result: "pinned" };
}

/** Slots read from repeated `track` values in order: `-`, empty, too long or repeated values are holes; trailing holes are trimmed. */
export function parseTrack(values: readonly string[]): (string | null)[] {
    const slots: (string | null)[] = [];
    for (const raw of values.slice(0, TRACK_MAX)) {
        const value = raw.trim();
        const hole =
            value === "" ||
            value === TRACK_HOLE ||
            value.length > MAX_URI ||
            slots.includes(value);
        slots.push(hole ? null : value);
    }
    while (slots.length > 0 && slots[slots.length - 1] === null) slots.pop();
    return slots;
}

export function serializeTrack(slots: readonly (string | null)[]): string[] {
    return slots.map((uri) => uri ?? TRACK_HOLE);
}

/** Whether the materials `carried` meet the followed ones: any of them, or all under `all`; true when none is followed. Exact uris only. */
export function meetsTrack(
    carried: ReadonlySet<string>,
    tracked: readonly TrackedMaterial[],
    mode: FocusMode,
): boolean {
    if (tracked.length === 0) return true;
    return mode === "all"
        ? tracked.every(({ uri }) => carried.has(uri))
        : tracked.some(({ uri }) => carried.has(uri));
}
