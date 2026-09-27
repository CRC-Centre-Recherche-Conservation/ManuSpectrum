<script setup lang="ts">
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";

import type { FileLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/** The curves of one XY window, « A1 · file name », in slot order, under the analysis they belong to. */
const props = defineProps<{ curves: readonly FileLine[] }>();
</script>

<template>
    <ol class="xy-curve-list">
        <li
            v-for="curve in props.curves"
            :key="`${curve.key}|${curve.file.id}`"
            :data-key="curve.key"
        >
            <span class="curve"
                >{{ slotLabel(curve.slot) }} · {{ curve.file.name }}</span
            >
            <span
                class="analysis"
                :lang="curve.analysis.name.lang"
                >{{ curve.analysis.name.value }}</span
            >
        </li>
    </ol>
</template>

<style scoped>
.xy-curve-list {
    display: grid;
    gap: 0.25rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.xy-curve-list li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0 0.5rem;
}

.xy-curve-list .curve {
    font-family: var(--font-mono);
    overflow-wrap: anywhere;
}

.xy-curve-list .analysis {
    color: var(--ink-muted);
    font-size: 0.75rem;
}
</style>
