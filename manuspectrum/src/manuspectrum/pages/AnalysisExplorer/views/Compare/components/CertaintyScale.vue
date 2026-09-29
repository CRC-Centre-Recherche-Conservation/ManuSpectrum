<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import {
    CERTAINTY_STEPS,
    certaintySteps,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/materials.ts";

import type { RankedValue } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * A certainty on an ordered scale of four steps filled from the start
 * (`certaintySteps`), its label beside; `best` marks the most certain of
 * several identified materials. Without a confidence, a dash.
 */
const props = withDefaults(
    defineProps<{
        confidence: RankedValue | null;
        best?: boolean;
    }>(),
    { best: false },
);

const { $gettext, interpolate } = useGettext();

const steps = computed(() =>
    props.confidence ? certaintySteps(props.confidence) : 0,
);
const title = computed(() =>
    props.confidence
        ? interpolate(
              $gettext("%{label} (%{n} of %{total})"),
              {
                  label: props.confidence.label.value,
                  n: steps.value,
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
        :title="title"
    >
        <span
            class="steps"
            aria-hidden="true"
        >
            <i
                v-for="step in CERTAINTY_STEPS"
                :key="step"
                :class="{ on: step <= steps }"
            ></i>
        </span>
        <span :lang="props.confidence.label.lang">{{
            props.confidence.label.value
        }}</span>
        <span
            v-if="props.best"
            class="best"
            >{{ $gettext("best") }}</span
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
    gap: 0.375rem;
    color: var(--ink-muted);
    font-size: 0.75rem;
    white-space: nowrap;
}

.certainty-scale .steps {
    display: inline-flex;
    gap: 0.125rem;
}

.certainty-scale .steps i {
    inline-size: 0.5rem;
    block-size: 0.5rem;
    border-radius: 50%;
    box-shadow: inset 0 0 0 0.0625rem var(--ink-muted);
}

.certainty-scale .steps i.on {
    background: var(--ink-muted);
}

.certainty-scale .best {
    color: var(--ink-muted);
    font-size: 0.625rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
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
    .certainty-scale .steps i.on {
        background: CanvasText;
    }
}
</style>
