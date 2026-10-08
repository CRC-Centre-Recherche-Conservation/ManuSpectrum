<script setup lang="ts">
import { useTemplateRef } from "vue";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";

/**
 * The way back to the screen a document was opened from: a pill with a left
 * arrow and a label that names the destination. `element` is its button,
 * for a screen that moves the focus to it.
 */
defineProps<{ label: string }>();

const emit = defineEmits<{ (event: "click", payload: MouseEvent): void }>();

const element = useTemplateRef<HTMLButtonElement>("button");

defineExpose({ element });

function onClick(event: MouseEvent): void {
    emit("click", event);
}
</script>

<template>
    <button
        ref="button"
        type="button"
        class="return-pill"
        @click="onClick"
    >
        <svg
            class="icon"
            :viewBox="ICON_VIEW_BOX"
            aria-hidden="true"
            focusable="false"
        >
            <path
                v-for="(path, index) in ICONS['arrow-left']"
                :key="index"
                :d="path"
            />
        </svg>
        <span>{{ label }}</span>
    </button>
</template>

<style scoped>
.return-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: 2.25rem;
    padding-inline: 0.875rem;
    border: 0.0625rem solid var(--ink);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.8125rem;
    font-weight: 600;
    cursor: pointer;
}

.return-pill:hover {
    background: var(--ink);
    color: var(--surface);
}

.return-pill:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.return-pill .icon {
    inline-size: 1rem;
    block-size: 1rem;
    fill: currentColor;
}

@media (forced-colors: active) {
    .return-pill .icon {
        fill: ButtonText;
    }
}
</style>
