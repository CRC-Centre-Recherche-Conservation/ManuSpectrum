<script setup lang="ts">
import { useTemplateRef } from "vue";

import HelpTip from "@/manuspectrum/pages/AnalysisExplorer/components/HelpTip.vue";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";

import type { IconName } from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";

/**
 * A button that shows only an icon (`icons.ts`, primeicons). Its `label` is
 * its accessible name and its tooltip at once (`HelpTip` in the label
 * role), so it is read once; a `description` is shown in the tooltip under
 * the label and is the button's description. `pressed` makes it a toggle
 * (`aria-pressed`); left null it is a plain button. A disabled button stays
 * focusable (`aria-disabled`) and emits no click. Other attributes
 * (`data-action`, `aria-expanded`…) go to the button; `element` is the
 * button, for a parent that moves the focus to it. Its target is
 * `--explorer-target` square.
 */
defineOptions({ inheritAttrs: false });

const props = withDefaults(
    defineProps<{
        icon: IconName;
        label: string;
        description?: string;
        pressed?: boolean | null;
        disabled?: boolean;
        tipPlacement?: "above" | "below";
        tipAlign?: "start" | "end";
    }>(),
    {
        description: "",
        pressed: null,
        disabled: false,
        tipPlacement: "below",
        tipAlign: "end",
    },
);

const emit = defineEmits<{ (event: "click", payload: MouseEvent): void }>();

const element = useTemplateRef<HTMLButtonElement>("button");

defineExpose({ element });

function onClick(event: MouseEvent): void {
    if (!props.disabled) emit("click", event);
}
</script>

<template>
    <HelpTip
        class="icon-button"
        mode="label"
        :text="props.label"
        :detail="props.description"
        :placement="props.tipPlacement"
        :align="props.tipAlign"
    >
        <template #default="{ labelledby, describedby }">
            <button
                v-bind="$attrs"
                ref="button"
                type="button"
                class="icon-button-control"
                :aria-labelledby="labelledby"
                :aria-describedby="describedby"
                :aria-pressed="props.pressed ?? undefined"
                :aria-disabled="props.disabled ? 'true' : undefined"
                @click="onClick"
            >
                <svg
                    class="icon"
                    :viewBox="ICON_VIEW_BOX"
                    aria-hidden="true"
                    focusable="false"
                >
                    <path
                        v-for="(path, index) in ICONS[props.icon]"
                        :key="index"
                        :d="path"
                    />
                </svg>
            </button>
        </template>
    </HelpTip>
</template>

<style scoped>
.icon-button .icon-button-control {
    display: inline-grid;
    place-items: center;
    min-inline-size: var(--explorer-target, 2rem);
    min-block-size: var(--explorer-target, 2rem);
    padding: 0;
    border: 0.0625rem solid transparent;
    border-radius: 0.375rem;
    background: transparent;
    color: var(--ink-muted);
    cursor: pointer;
}

.icon-button .icon-button-control:hover {
    background: var(--bg-alt);
    color: var(--ink);
}

.icon-button .icon-button-control[aria-pressed="true"] {
    border-color: var(--ink);
    background: var(--bg-alt);
    color: var(--ink);
}

.icon-button .icon-button-control[aria-disabled="true"] {
    background: transparent;
    color: var(--ink-dim);
    cursor: default;
}

.icon-button .icon-button-control:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.0625rem;
}

.icon-button .icon {
    inline-size: 1.125rem;
    block-size: 1.125rem;
    fill: currentColor;
}

@media (forced-colors: active) {
    .icon-button .icon {
        fill: ButtonText;
    }
}
</style>
