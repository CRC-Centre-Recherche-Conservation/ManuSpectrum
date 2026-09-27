<script setup lang="ts">
import { computed } from "vue";

import { techniqueClass } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";

/**
 * The code of a technique in a round chip of its family colour, as on the
 * folio markers; ink outline without a colour. `size: "small"` is the chip
 * of the folio legend, drawn over the stage. `decorative: false` lets
 * assistive technologies read the code.
 */
const props = withDefaults(
    defineProps<{
        code: string;
        colour: number | null;
        size?: "medium" | "small";
        decorative?: boolean;
    }>(),
    { size: "medium", decorative: true },
);

const colourClass = computed(() => techniqueClass("code", props.colour));
</script>

<template>
    <span
        class="technique-code code"
        :class="[
            colourClass,
            { 'technique-code--small': props.size === 'small' },
        ]"
        :aria-hidden="props.decorative ? 'true' : undefined"
        >{{ props.code }}</span
    >
</template>

<style scoped>
.technique-code {
    display: inline-grid;
    flex: none;
    place-items: center;
    box-sizing: border-box;
    min-inline-size: 1.5rem;
    block-size: 1.5rem;
    padding-inline: 0.25rem;
    border: 0.125rem solid var(--surface);
    border-radius: 999rem;
    background: var(--ink);
    color: var(--stage);
    font: 600 0.625rem var(--font-body);
    white-space: nowrap;
}

.technique-code.code--tech-1 {
    background: var(--tech-1);
}

.technique-code.code--tech-2 {
    background: var(--tech-2);
}

.technique-code.code--tech-3 {
    background: var(--tech-3);
}

.technique-code.code--tech-4 {
    background: var(--tech-4);
}

.technique-code.code--tech-5 {
    background: var(--tech-5);
}

.technique-code.code--tech-6 {
    background: var(--tech-6);
}

.technique-code.code--tech-7 {
    background: var(--tech-7);
}

.technique-code.code--tech-8 {
    background: var(--tech-8);
}

.technique-code.code--tech-9 {
    background: var(--tech-9);
}

.technique-code.code--tech-10 {
    background: var(--tech-10);
}

.technique-code.code--ink {
    border-color: var(--ink);
    background: var(--surface);
    color: var(--ink);
}

.technique-code.technique-code--small {
    min-inline-size: 1.25rem;
    block-size: 1.25rem;
    padding-inline: 0.125rem;
    border-width: 0.0625rem;
    font-size: 0.5625rem;
    white-space: inherit;
}

.technique-code.technique-code--small.code--ink {
    border-color: var(--surface);
}
</style>
