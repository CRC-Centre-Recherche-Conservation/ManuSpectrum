<script setup lang="ts">
import { computed } from "vue";

import { techniqueClass } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";

import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** A technique as every screen marks it: the dot of its family colour, its code, and its label when given. */
const props = withDefaults(
    defineProps<{
        code: string;
        colour: number | null;
        label?: Label | null;
    }>(),
    { label: null },
);

const dotClass = computed(() => techniqueClass("dot", props.colour));
</script>

<template>
    <span class="technique-tag">
        <span
            class="dot"
            :class="dotClass"
            aria-hidden="true"
        ></span>
        <span class="code">{{ props.code }}</span>
        <span
            v-if="props.label"
            class="name"
            :lang="props.label.lang || undefined"
            >{{ props.label.value }}</span
        >
    </span>
</template>

<style scoped>
.technique-tag {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0 0.375rem;
}

.technique-tag .dot {
    flex: none;
    inline-size: 0.625rem;
    block-size: 0.625rem;
    border-radius: 50%;
}

.technique-tag .dot--ink {
    border: 0.125rem solid var(--ink);
}

.technique-tag .code {
    font-family: var(--font-mono);
    font-weight: 600;
}

.technique-tag .dot--tech-1 {
    background: var(--tech-1);
}

.technique-tag .dot--tech-2 {
    background: var(--tech-2);
}

.technique-tag .dot--tech-3 {
    background: var(--tech-3);
}

.technique-tag .dot--tech-4 {
    background: var(--tech-4);
}

.technique-tag .dot--tech-5 {
    background: var(--tech-5);
}

.technique-tag .dot--tech-6 {
    background: var(--tech-6);
}

.technique-tag .dot--tech-7 {
    background: var(--tech-7);
}

.technique-tag .dot--tech-8 {
    background: var(--tech-8);
}

.technique-tag .dot--tech-9 {
    background: var(--tech-9);
}

.technique-tag .dot--tech-10 {
    background: var(--tech-10);
}
</style>
