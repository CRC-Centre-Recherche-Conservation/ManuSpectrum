<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";

const CHANGE_EVENT = "change" as const;

/**
 * The switch of the document screen that shows (on) or hides (off) the
 * analyses the filters leave out. `hiddenCount` is how many the document
 * has; the screen shows the switch only when there are some.
 */
const props = defineProps<{ shown: boolean; hiddenCount: number }>();

const emit = defineEmits<{
    (event: typeof CHANGE_EVENT, shown: boolean): void;
}>();

const { $gettext, interpolate } = useGettext();

const label = computed(() =>
    interpolate(
        $gettext("Analyses outside the filters (%{n})"),
        { n: props.hiddenCount },
        true,
    ),
);
const paths = computed(() => ICONS[props.shown ? "eye" : "eye-slash"]);

function onClick(): void {
    emit(CHANGE_EVENT, !props.shown);
}
</script>

<template>
    <button
        type="button"
        class="outside-filters-toggle"
        role="switch"
        :aria-checked="props.shown ? 'true' : 'false'"
        @click="onClick"
    >
        <svg
            class="icon"
            :viewBox="ICON_VIEW_BOX"
            aria-hidden="true"
            focusable="false"
        >
            <path
                v-for="(path, index) in paths"
                :key="index"
                :d="path"
            />
        </svg>
        <span class="label">{{ label }}</span>
        <span
            class="track"
            aria-hidden="true"
        >
            <span class="thumb"></span>
        </span>
    </button>
</template>

<style scoped>
.outside-filters-toggle {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: none;
    border-radius: 0.25rem;
    background: none;
    color: var(--ink);
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
}

.outside-filters-toggle:hover {
    background: var(--bg-alt);
}

.outside-filters-toggle:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.outside-filters-toggle .icon {
    inline-size: 1.125rem;
    block-size: 1.125rem;
    fill: currentcolor;
}

.outside-filters-toggle .track {
    display: inline-flex;
    align-items: center;
    inline-size: 2rem;
    block-size: 1.125rem;
    padding: 0.125rem;
    border: 0.0625rem solid var(--ink-muted);
    border-radius: 1rem;
    background: transparent;
}

.outside-filters-toggle .thumb {
    inline-size: 0.75rem;
    block-size: 0.75rem;
    border-radius: 50%;
    background: var(--ink-muted);
}

.outside-filters-toggle[aria-checked="true"] .track {
    border-color: var(--blue-text);
    background: var(--blue-text);
    justify-content: flex-end;
}

.outside-filters-toggle[aria-checked="true"] .thumb {
    background: var(--bg);
}
</style>
