import { getCurrentScope, onScopeDispose, shallowRef } from "vue";

import {
    REGISTRATION_STORAGE_KEY,
    UNPLACED,
    keepRecent,
    parseRegistrations,
    serializeRegistrations,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/registration-store.ts";
import {
    readStorage,
    removeStorage,
    writeStorage,
} from "@/manuspectrum/public/safe-storage.ts";

import type { ShallowRef } from "vue";
import type {
    Capture,
    Registration,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/registration-store.ts";
import type {
    Box,
    Quarter,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";

type Entries = Record<string, Registration>;

let shared: ShallowRef<Entries> | null = null;

function read(): Entries {
    return parseRegistrations(readStorage(REGISTRATION_STORAGE_KEY));
}

function state(): ShallowRef<Entries> {
    shared ??= shallowRef(read());
    return shared;
}

/** Reads the stored registrations again (a spec reset the storage). */
export function reloadRegistrations(): void {
    state().value = read();
}

/** Scopes using the registrations: the `storage` listener lives while there is one. */
let listeners = 0;

function onStorage(event: StorageEvent): void {
    if (event.key !== null && event.key !== REGISTRATION_STORAGE_KEY) return;
    const next = read();
    if (JSON.stringify(next) !== JSON.stringify(state().value)) {
        state().value = next;
    }
}

function commit(entries: Entries): void {
    const next = keepRecent(entries);
    state().value = next;
    if (Object.keys(next).length === 0) {
        removeStorage(REGISTRATION_STORAGE_KEY);
    } else {
        writeStorage(REGISTRATION_STORAGE_KEY, serializeRegistrations(next));
    }
}

function without(entries: Entries, id: string): Entries {
    const next = { ...entries };
    delete next[id];
    return next;
}

/**
 * Where the reader laid each imaging layer on the folio (box, quarter turns)
 * and the capture taken from it, per analysis, kept in this browser only. One
 * copy per tab; another tab's write is adopted through the `storage` event.
 */
export function useRegistration() {
    const entries = state();
    if (getCurrentScope()) {
        if (listeners === 0) window.addEventListener("storage", onStorage);
        listeners += 1;
        onScopeDispose(() => {
            listeners -= 1;
            if (listeners === 0) {
                window.removeEventListener("storage", onStorage);
            }
        });
    }

    function get(analysisId: string): Registration | null {
        return entries.value[analysisId] ?? null;
    }

    function setPlace(
        analysisId: string,
        canvas: string,
        box: Box,
        quarter: Quarter,
    ): void {
        const held = get(analysisId);
        commit({
            ...entries.value,
            [analysisId]: {
                canvas,
                box,
                quarter,
                capture: held?.capture ?? null,
                touched: Date.now(),
            },
        });
    }

    function setCapture(analysisId: string, capture: Capture): void {
        const held = get(analysisId);
        commit({
            ...entries.value,
            [analysisId]: {
                canvas: held?.canvas ?? capture.canvas,
                box: held?.box ?? UNPLACED,
                quarter: held?.quarter ?? 0,
                capture,
                touched: Date.now(),
            },
        });
    }

    function clearCapture(analysisId: string): void {
        const held = get(analysisId);
        if (held === null) return;
        if (held.box.w === UNPLACED.w && held.box.h === UNPLACED.h) {
            commit(without(entries.value, analysisId));
            return;
        }
        commit({
            ...entries.value,
            [analysisId]: { ...held, capture: null, touched: Date.now() },
        });
    }

    /** Forgets the box and the turns; a capture keeps its entry. */
    function reset(analysisId: string): void {
        const held = get(analysisId);
        if (held === null) return;
        if (held.capture === null) {
            commit(without(entries.value, analysisId));
            return;
        }
        commit({
            ...entries.value,
            [analysisId]: {
                ...held,
                box: UNPLACED,
                quarter: 0,
                touched: Date.now(),
            },
        });
    }

    return { entries, get, setPlace, setCapture, clearCapture, reset };
}
