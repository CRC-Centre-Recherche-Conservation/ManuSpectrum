import { readonly, ref } from "vue";

import {
    readStorage,
    removeStorage,
    writeStorage,
} from "@/manuspectrum/public/safe-storage.ts";

import type { Ref } from "vue";

export const RAIL_STORAGE_KEY = "ms-explorer-rail-v1";
const WIDE_MODE = "wide";

export interface RailWidth {
    /** True while the reader asked for the wide filter column. */
    wide: Readonly<Ref<boolean>>;
    toggleWide: () => void;
}

/**
 * The width mode of the filter column, one for the whole browser: the
 * default (`--explorer-rail`) or wide (`--explorer-rail-wide`, each view
 * clamps it to what its content leaves). Read once on creation from
 * `ms-explorer-rail-v1` (the string « wide », anything else is the default),
 * not synced across tabs. Storage goes through `safe-storage`: blocked
 * storage keeps the choice for the tab only.
 */
export function useRailWidth(): RailWidth {
    const wide = ref(readStorage(RAIL_STORAGE_KEY) === WIDE_MODE);

    function toggleWide(): void {
        wide.value = !wide.value;
        if (wide.value) writeStorage(RAIL_STORAGE_KEY, WIDE_MODE);
        else removeStorage(RAIL_STORAGE_KEY);
    }

    return { wide: readonly(wide), toggleWide };
}
