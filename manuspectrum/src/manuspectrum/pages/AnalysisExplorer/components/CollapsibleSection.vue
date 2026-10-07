<script setup lang="ts">
import { computed, useId } from "vue";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";

const TOGGLE_EVENT = "toggle" as const;

/**
 * A titled block the reader can fold. The title is a button (`aria-expanded`,
 * `aria-controls`) in a heading; folded, the heading shows the one-line
 * `summary`. The `actions` slot stays in the header, folded or not; the
 * default slot is the body, kept in the page (hidden) while folded. The
 * parent owns the state: `open` in, `toggle` out with the next value.
 */
const props = defineProps<{
    title: string;
    open: boolean;
    summary?: string;
}>();

const emit = defineEmits<{
    (event: typeof TOGGLE_EVENT, open: boolean): void;
}>();

const headingId = useId();
const contentId = useId();

const chevron = computed(
    () => ICONS[props.open ? "chevron-down" : "chevron-right"],
);
</script>

<template>
    <section
        class="collapsible-section"
        :aria-labelledby="headingId"
    >
        <div class="head">
            <h4
                :id="headingId"
                class="heading"
            >
                <button
                    type="button"
                    class="toggle"
                    :aria-expanded="props.open ? 'true' : 'false'"
                    :aria-controls="contentId"
                    @click="emit(TOGGLE_EVENT, !props.open)"
                >
                    <svg
                        class="chevron"
                        :viewBox="ICON_VIEW_BOX"
                        aria-hidden="true"
                        focusable="false"
                    >
                        <path
                            v-for="(path, index) in chevron"
                            :key="index"
                            :d="path"
                        />
                    </svg>
                    <span class="title">{{ props.title }}</span>
                    <span
                        v-if="!props.open && props.summary"
                        class="summary"
                        >{{ props.summary }}</span
                    >
                </button>
            </h4>
            <div class="actions">
                <slot name="actions" />
            </div>
        </div>
        <div
            v-show="props.open"
            :id="contentId"
            class="content"
        >
            <slot />
        </div>
    </section>
</template>

<style scoped>
.collapsible-section {
    display: grid;
    gap: 0.5rem;
}

.collapsible-section .head {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.collapsible-section .heading {
    flex: 1;
    min-inline-size: 0;
    margin: 0;
}

.collapsible-section .toggle {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    inline-size: 100%;
    min-block-size: var(--explorer-target, 2.75rem);
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.collapsible-section .toggle:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.0625rem;
}

.collapsible-section .chevron {
    flex: none;
    inline-size: 1rem;
    block-size: 1rem;
    fill: currentcolor;
}

.collapsible-section .title {
    font-weight: 600;
}

.collapsible-section .summary {
    min-inline-size: 0;
    overflow: hidden;
    color: var(--ink-muted);
    font-size: 0.875rem;
    font-weight: 400;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.collapsible-section .actions {
    display: flex;
    flex: none;
    align-items: center;
    gap: 0.25rem;
}
</style>
