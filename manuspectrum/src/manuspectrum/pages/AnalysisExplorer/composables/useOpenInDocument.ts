import { inject } from "vue";

import { SCREEN_FOCUS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    documentHref,
    snapshotOf,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";

import type { DocumentTarget } from "@/manuspectrum/pages/AnalysisExplorer/selection/place.ts";

/** A primary-button click with no modifier key: the one the application answers itself. */
export function isPlainClick(event: MouseEvent): boolean {
    return (
        !event.defaultPrevented &&
        event.button === 0 &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.shiftKey &&
        !event.altKey
    );
}

/**
 * The one way a link to a document screen behaves. `hrefOf` is the address
 * the link carries; `open` answers a click on it: a plain click is handled
 * here (`preventDefault`, then one store change that opens the document, its
 * page, the focused record and the folio view, so the address records one
 * history entry) and the screen's heading takes the keyboard focus; a click
 * with a modifier key or a non-primary button is left to the browser. `open`
 * returns whether the application navigated.
 */
export function useOpenInDocument() {
    const store = useExplorerStore();
    const screenFocus = inject(SCREEN_FOCUS_KEY, null);

    function hrefOf(target: DocumentTarget): string {
        return documentHref(
            snapshotOf(store),
            target.document,
            target.canvas,
            target.focus,
        );
    }

    function open(target: DocumentTarget, event: MouseEvent): boolean {
        if (!isPlainClick(event)) return false;
        event.preventDefault();
        if (screenFocus) screenFocus.value = true;
        store.openInDocument(target);
        return true;
    }

    return { hrefOf, open };
}
