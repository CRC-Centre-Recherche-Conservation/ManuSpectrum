<script setup lang="ts">
import { computed } from "vue";

import { focusHue } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";

/**
 * The disc of a focus slot: its number on its hue. `size` follows where
 * it sits: `small` in a window header, `medium` in the toolbar and the
 * trail, `large` in the legend of the focus. Hidden from assistive
 * technologies: the text beside it names the slot.
 */
const props = withDefaults(
    defineProps<{
        number: number;
        size?: "small" | "medium" | "large";
    }>(),
    { size: "medium" },
);

const hue = computed(() => ({ "--h": focusHue(props.number) }));
</script>

<template>
    <i
        class="focus-slot-dot"
        aria-hidden="true"
        :data-size="props.size"
        :style="hue"
        >{{ props.number }}</i
    >
</template>

<style scoped>
.focus-slot-dot {
    display: inline-grid;
    flex: none;
    place-items: center;
    inline-size: 1.125rem;
    block-size: 1.125rem;
    border-radius: 50%;
    background: var(--h);
    color: var(--focus-on, var(--surface));
    font: 700 0.625rem/1 var(--font-mono);
    font-style: normal;
    font-variant-numeric: tabular-nums;
}

.focus-slot-dot[data-size="small"] {
    inline-size: 0.875rem;
    block-size: 0.875rem;
    font-size: 0.5rem;
}

.focus-slot-dot[data-size="large"] {
    inline-size: 1.25rem;
    block-size: 1.25rem;
    font-size: 0.6875rem;
}

@media (forced-colors: active) {
    .focus-slot-dot {
        forced-color-adjust: none;
    }
}
</style>
