// Access to window.localStorage throws a SecurityError when the browser blocks
// site data (private windows, strict cookie settings). Every read and write of
// the public pages goes through these helpers.

const PROBE_KEY = "ms-storage-probe";

export function readStorage(key: string): string | null {
    try {
        return window.localStorage.getItem(key);
    } catch {
        return null;
    }
}

export function writeStorage(key: string, value: string): boolean {
    try {
        window.localStorage.setItem(key, value);
        return true;
    } catch {
        return false;
    }
}

export function createMemoryStorage(): Storage {
    const entries = new Map<string, string>();
    return {
        get length(): number {
            return entries.size;
        },
        clear(): void {
            entries.clear();
        },
        getItem(key: string): string | null {
            return entries.get(key) ?? null;
        },
        key(index: number): string | null {
            return [...entries.keys()][index] ?? null;
        },
        removeItem(key: string): void {
            entries.delete(key);
        },
        setItem(key: string, value: string): void {
            entries.set(key, String(value));
        },
    };
}

/**
 * Replace a blocked window.localStorage with an in-memory Storage.
 *
 * Third-party code reads localStorage without a guard
 * (arches_vue_components' createVueApplication reads the dark-mode key), so a
 * blocked storage would stop the application before it mounts.
 */
export function guardLocalStorage(): void {
    try {
        window.localStorage.getItem(PROBE_KEY);
        return;
    } catch {
        Object.defineProperty(window, "localStorage", {
            configurable: true,
            value: createMemoryStorage(),
        });
    }
}
