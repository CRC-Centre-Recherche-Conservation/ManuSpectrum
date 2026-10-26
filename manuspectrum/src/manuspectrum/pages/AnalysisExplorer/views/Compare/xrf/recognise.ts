import type { FileViewer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** The preset key of the stored XRF configurations. */
const XRF_PRESET_KEY = "xrf";

/** The x part of an XRF `axisKey` (`<y>|<x>|<direction>`, casefolded by the server). */
const XRF_X_AXIS = "energy (kev)";

/** Whether a file is an XRF spectrum: the `xrf` preset, else an x axis in keV (`FileViewer.axisKey` is `y|x|asc` or `y|x|desc`). */
export function isXrfViewer(
    viewer: Pick<FileViewer, "presetKey" | "axisKey">,
): boolean {
    if (viewer.presetKey === XRF_PRESET_KEY) return true;
    const x = viewer.axisKey?.split("|")[1];
    return x !== undefined && x.trim().toLowerCase() === XRF_X_AXIS;
}
