<script setup lang="ts">
import { computed } from "vue";

import { techniqueClass } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";

import type {
    FacetKey,
    TechniqueMark,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * The mark drawn before a facet value's label, decorative (`aria-hidden`):
 * a technique carrying a mark gets the dot of its colour (an implied
 * ancestor carries none, so no dot), a value with a swatch the square of that
 * colour with an inner rim (white and beige stay visible), anything else
 * nothing. `dim` pales the swatch (a colour with no hit).
 */
const props = withDefaults(
    defineProps<{
        facetKey: FacetKey;
        mark: TechniqueMark | null;
        swatch: string | null;
        dim?: boolean;
    }>(),
    { dim: false },
);

const dotClass = computed(() =>
    props.facetKey === "technique" && props.mark
        ? techniqueClass("dot", props.mark.colour)
        : null,
);
</script>

<template>
    <span
        v-if="dotClass"
        class="facet-mark dot"
        :class="dotClass"
        aria-hidden="true"
    ></span>
    <span
        v-else-if="props.swatch"
        class="facet-mark swatch"
        aria-hidden="true"
        :class="{ dim: props.dim }"
        :style="{ '--swatch': props.swatch }"
    ></span>
</template>

<style scoped>
.facet-mark.dot {
    flex: none;
    inline-size: 0.625rem;
    block-size: 0.625rem;
    border-radius: 50%;
}

.facet-mark.swatch {
    flex: none;
    inline-size: 1.125rem;
    block-size: 1.125rem;
    border-radius: 0.1875rem;
    background: var(--swatch);
    box-shadow: inset 0 0 0 0.0625rem var(--border-hover);
}

.facet-mark.swatch.dim {
    opacity: 0.5;
}

.facet-mark.dot--tech-1 {
    background: var(--tech-1);
}

.facet-mark.dot--tech-2 {
    background: var(--tech-2);
}

.facet-mark.dot--tech-3 {
    background: var(--tech-3);
}

.facet-mark.dot--tech-4 {
    background: var(--tech-4);
}

.facet-mark.dot--tech-5 {
    background: var(--tech-5);
}

.facet-mark.dot--tech-6 {
    background: var(--tech-6);
}

.facet-mark.dot--tech-7 {
    background: var(--tech-7);
}

.facet-mark.dot--tech-8 {
    background: var(--tech-8);
}

.facet-mark.dot--tech-9 {
    background: var(--tech-9);
}

.facet-mark.dot--tech-10 {
    background: var(--tech-10);
}

.facet-mark.dot--ink {
    border: 0.125rem solid var(--ink);
}
</style>
