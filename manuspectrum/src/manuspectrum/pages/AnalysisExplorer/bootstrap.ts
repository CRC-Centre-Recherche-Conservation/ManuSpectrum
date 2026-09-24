import AnalysisExplorer from "@/manuspectrum/pages/AnalysisExplorer/AnalysisExplorer.vue";

import { mountPublicApp } from "@/manuspectrum/public/mountPublicApp.ts";

// Looked for by check_explorer_bundle.sh: it must appear in the lazy
// analysis-explorer chunk and in no initial file of another entry.
export const EXPLORER_CHUNK_MARKER = "__MS_EXPLORER_CHUNK__";
const MOUNT_POINT_ID = "ms-explorer-app";

export async function startAnalysisExplorer(): Promise<void> {
    const mountPoint = document.getElementById(MOUNT_POINT_ID);
    if (!mountPoint) {
        return;
    }
    mountPoint.dataset.bundle = EXPLORER_CHUNK_MARKER;
    await mountPublicApp({
        component: AnalysisExplorer,
        mountPoint,
        initialProps: { connected: mountPoint.dataset.connected === "true" },
    });
}
