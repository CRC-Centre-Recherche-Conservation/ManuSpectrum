export type CheckState = "none" | "some" | "all";

export type TogglePlan =
    | { action: "add"; keys: string[] }
    | { action: "remove"; keys: string[] }
    | { action: "refused"; needed: number; free: number };

/** Whether none, some or all of the keys are held. No key at all is « none ». */
export function checkState(
    keys: readonly string[],
    held: ReadonlySet<string>,
): CheckState {
    const count = keys.filter((key) => held.has(key)).length;
    if (count === 0) return "none";
    return count === keys.length ? "all" : "some";
}

/**
 * What a select-all checkbox does: all held → remove them all; otherwise add
 * the missing ones, or refuse when they exceed the `free` places (never a
 * partial fill).
 */
export function planToggleAll(
    keys: readonly string[],
    held: ReadonlySet<string>,
    free: number,
): TogglePlan {
    if (checkState(keys, held) === "all") {
        return { action: "remove", keys: [...keys] };
    }
    const missing = keys.filter((key) => !held.has(key));
    if (missing.length > free) {
        return { action: "refused", needed: missing.length, free };
    }
    return { action: "add", keys: missing };
}
