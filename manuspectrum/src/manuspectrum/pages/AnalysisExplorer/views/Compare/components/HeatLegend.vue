<script setup lang="ts">
import { HEAT_STEPS } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/heat.ts";

const STEPS = Array.from({ length: HEAT_STEPS }, (_, index) => index + 1);

/**
 * The legend of a table shaded on the heat ramp: the smallest count,
 * the steps of the ramp, the largest count, then what the number counts
 * (`caption`).
 */
const props = defineProps<{ caption: string; max: number }>();
</script>

<template>
    <p class="heat-legend">
        <span class="end">1</span>
        <span
            class="ramp"
            aria-hidden="true"
        >
            <span
                v-for="step in STEPS"
                :key="step"
                class="step"
                :data-heat="step"
            ></span>
        </span>
        <span class="end">{{ props.max }}</span>
        <span class="caption">{{ props.caption }}</span>
    </p>
</template>

<style scoped>
.heat-legend {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.375rem;
    margin: 0;
    color: var(--ink-muted);
    font-size: 0.75rem;
}

.heat-legend .end {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
}

.heat-legend .ramp {
    display: inline-flex;
    gap: 0.125rem;
}

.heat-legend .step {
    inline-size: 1rem;
    block-size: 0.625rem;
    border-radius: 0.125rem;
}

.heat-legend .step[data-heat="1"] {
    background: var(--heat-1);
}

.heat-legend .step[data-heat="2"] {
    background: var(--heat-2);
}

.heat-legend .step[data-heat="3"] {
    background: var(--heat-3);
}

.heat-legend .step[data-heat="4"] {
    background: var(--heat-4);
}

.heat-legend .caption {
    padding-inline-start: 0.25rem;
}
</style>
