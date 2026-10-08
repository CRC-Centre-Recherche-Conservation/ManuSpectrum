import { getCurrentScope, onScopeDispose, shallowRef } from "vue";

import {
    LAYOUT_STORAGE_KEY,
    XRF_MAX_ANODES,
    XRF_MAX_ELEMENTS,
    readXrfSettings,
    writeXrfSettings,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";

import type { ShallowRef } from "vue";
import type {
    XrfAnode,
    XrfDetector,
    XrfSettings,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";

function defaults(): XrfSettings {
    return { detector: "sdd", anodes: {}, elements: [] };
}

function isDefault(settings: XrfSettings): boolean {
    return (
        settings.detector === "sdd" &&
        Object.keys(settings.anodes).length === 0 &&
        settings.elements.length === 0
    );
}

let shared: ShallowRef<XrfSettings> | null = null;

function state(): ShallowRef<XrfSettings> {
    shared ??= shallowRef(readXrfSettings() ?? defaults());
    return shared;
}

/** Reads the stored settings again (another tab wrote them, or a spec reset the storage). */
export function reloadXrfSettings(): void {
    state().value = readXrfSettings() ?? defaults();
}

/** Scopes using the settings: the `storage` listener lives while there is one. */
let listeners = 0;

function onStorage(event: StorageEvent): void {
    if (event.key !== null && event.key !== LAYOUT_STORAGE_KEY) return;
    const next = readXrfSettings() ?? defaults();
    if (JSON.stringify(next) !== JSON.stringify(state().value)) {
        state().value = next;
    }
}

function commit(next: XrfSettings): void {
    state().value = next;
    writeXrfSettings(isDefault(next) ? undefined : next);
}

/**
 * The XRF settings of the reader (detector, anode per analysis, lens
 * elements), one copy for every XRF window of the tab and saved with the
 * Compare layout. The lens elements are a list of their own: they never enter
 * the focus. Another tab's write to the layout record is adopted through the
 * `storage` event, as the Selection basket's is.
 */
export function useXrfSettings() {
    const settings = state();
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

    function setDetector(detector: XrfDetector): void {
        commit({ ...settings.value, detector });
    }

    /** Sets the anode of an analysis; null forgets the choice (the conditions' anode, else unknown). False when the list is full. */
    function setAnode(
        analysis: string,
        anode: XrfAnode | "none" | null,
    ): boolean {
        const anodes = { ...settings.value.anodes };
        if (anode === null) delete anodes[analysis];
        else if (
            analysis in anodes ||
            Object.keys(anodes).length < XRF_MAX_ANODES
        ) {
            anodes[analysis] = anode;
        } else return false;
        commit({ ...settings.value, anodes });
        return true;
    }

    /** Adds a lens element; false when it is there already or the list is full. */
    function addElement(symbol: string): boolean {
        const { elements } = settings.value;
        if (elements.includes(symbol) || elements.length >= XRF_MAX_ELEMENTS) {
            return false;
        }
        commit({ ...settings.value, elements: [...elements, symbol] });
        return true;
    }

    function removeElement(symbol: string): void {
        const { elements } = settings.value;
        if (!elements.includes(symbol)) return;
        commit({
            ...settings.value,
            elements: elements.filter((held) => held !== symbol),
        });
    }

    function toggleElement(symbol: string): boolean {
        if (settings.value.elements.includes(symbol)) {
            removeElement(symbol);
            return false;
        }
        return addElement(symbol);
    }

    return {
        settings,
        setDetector,
        setAnode,
        addElement,
        removeElement,
        toggleElement,
    };
}
