import { RANGE_PRESETS } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";

import type { RangePreset } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";

/** The range select's value once the reader zoomed by hand. */
export const CUSTOM_RANGE = "custom";

/** The energy-range preset named `key`; undefined for « custom » and unknown keys. */
export function rangePresetOf(key: string): RangePreset | undefined {
    return RANGE_PRESETS.find((preset) => preset.key === key);
}
