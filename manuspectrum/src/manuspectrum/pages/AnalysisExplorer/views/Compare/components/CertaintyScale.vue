<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import {
    CERTAINTY_STEPS,
    certaintySteps,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/materials.ts";

import type { RankedValue } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * A certainty on four rising bars, filled up to its step
 * (`certaintySteps`, `data-step`, 4 the most certain) in that step's hue
 * (`--cert-1…4`), its label beside: the bars are graphic only, the label
 * says it. Without a confidence, a dash.
 */
const props = defineProps<{ confidence: RankedValue | null }>();

const { $gettext, interpolate } = useGettext();

const step = computed(() =>
    props.confidence ? certaintySteps(props.confidence) : 0,
);
const title = computed(() =>
    props.confidence
        ? interpolate(
              $gettext("%{label} (%{n} of %{total})"),
              {
                  label: props.confidence.label.value,
                  n: step.value,
                  total: CERTAINTY_STEPS,
              },
              true,
          )
        : undefined,
);
</script>

<template>
    <span
        v-if="props.confidence"
        class="certainty-scale"
        :data-step="step"
        :title="title"
    >
        <span
            class="bars"
            aria-hidden="true"
        >
            <i
                v-for="bar in CERTAINTY_STEPS"
                :key="bar"
                :class="{ on: bar <= step }"
            ></i>
        </span>
        <span
            class="label"
            :lang="props.confidence.label.lang"
            >{{ props.confidence.label.value }}</span
        >
    </span>
    <span
        v-else
        class="certainty-scale none"
    >
        <span aria-hidden="true">—</span>
        <span class="visually-hidden">{{ $gettext("Not stated") }}</span>
    </span>
</template>

<style scoped>
.certainty-scale {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--ink);
    font-size: 0.75rem;
    white-space: nowrap;
}

.certainty-scale .bars {
    display: inline-flex;
    align-items: flex-end;
    gap: 0.125rem;
    block-size: 0.875rem;
}

.certainty-scale .bars i {
    inline-size: 0.3125rem;
    border-radius: 0.0625rem;
    background: var(--cert-track);
}

.certainty-scale .bars i:nth-child(1) {
    block-size: 35%;
}

.certainty-scale .bars i:nth-child(2) {
    block-size: 55%;
}

.certainty-scale .bars i:nth-child(3) {
    block-size: 78%;
}

.certainty-scale .bars i:nth-child(4) {
    block-size: 100%;
}

.certainty-scale[data-step="4"] .bars i.on {
    background: var(--cert-4);
}

.certainty-scale[data-step="3"] .bars i.on {
    background: var(--cert-3);
}

.certainty-scale[data-step="2"] .bars i.on {
    background: var(--cert-2);
}

.certainty-scale[data-step="1"] .bars i.on {
    background: transparent;
    box-shadow: inset 0 0 0 0.0625rem var(--cert-3);
}

.certainty-scale[data-step="4"] .label {
    color: var(--cert-4);
    font-weight: 600;
}

.certainty-scale[data-step="1"] .label {
    color: var(--ink-muted);
    font-style: italic;
}

.certainty-scale.none {
    color: var(--ink-dim);
}

.certainty-scale .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

@media (forced-colors: active) {
    .certainty-scale .bars i {
        forced-color-adjust: none;
        background: Canvas;
        box-shadow: inset 0 0 0 0.0625rem GrayText;
    }

    .certainty-scale .bars i.on,
    .certainty-scale[data-step="1"] .bars i.on {
        background: CanvasText;
        box-shadow: none;
    }
}
</style>
