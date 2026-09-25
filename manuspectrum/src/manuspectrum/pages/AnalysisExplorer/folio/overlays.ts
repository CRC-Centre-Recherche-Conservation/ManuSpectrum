import type { LatLng } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";

export interface FolioOverlay {
    key: string;
    url: string;
    bounds: [LatLng, LatLng];
    opacity: number;
    label: string;
}
