<script setup lang="ts">
import { inject } from "vue";
import { useClipboard } from "@vueuse/core";
import { useGettext } from "vue3-gettext";

import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

/**
 * A button that copies `text` to the clipboard (the Clipboard API, else the
 * browser's copy command), says « Copied » on itself for a moment and through
 * the shell's live region. Disabled while `text` is empty. With `iconOnly`
 * it shows a copy icon, a check once copied, and `label` names it.
 */
const props = withDefaults(
    defineProps<{ text: string; label: string; iconOnly?: boolean }>(),
    { iconOnly: false },
);

const announce = inject(ANNOUNCE_KEY, () => undefined);

const { $gettext } = useGettext();
const { copy, copied } = useClipboard({ legacy: true });

async function copyText(): Promise<void> {
    if (!props.text) return;
    await copy(props.text);
    announce($gettext("Copied"));
}
</script>

<template>
    <button
        v-if="props.iconOnly"
        type="button"
        class="copy-button icon"
        :disabled="!props.text"
        :aria-label="props.label"
        :title="props.label"
        @click="copyText"
    >
        <svg
            v-if="copied"
            class="check"
            viewBox="0 0 16 16"
            aria-hidden="true"
        >
            <path d="M3 8.5 6.5 12 13 4.5" />
        </svg>
        <svg
            v-else
            class="copy"
            viewBox="0 0 16 16"
            aria-hidden="true"
        >
            <rect
                x="5.5"
                y="5.5"
                width="8"
                height="8"
                rx="1.5"
            />
            <path
                d="M10.5 3.5v-.5A1.5 1.5 0 0 0 9 1.5H4A1.5 1.5 0 0 0 2.5 3v5A1.5 1.5 0 0 0 4 9.5h.5"
            />
        </svg>
    </button>
    <button
        v-else
        type="button"
        class="copy-button"
        :disabled="!props.text"
        @click="copyText"
    >
        <span>{{ props.label }}</span>
        <span
            v-if="copied"
            class="done"
            aria-hidden="true"
            >✓ {{ $gettext("Copied") }}</span
        >
    </button>
</template>

<style scoped>
.copy-button {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
}

.copy-button.icon {
    justify-content: center;
    min-inline-size: var(--explorer-target, 2.75rem);
    padding-inline: 0;
    border-radius: 0.375rem;
}

.copy-button.icon svg {
    inline-size: 1rem;
    block-size: 1rem;
    fill: none;
    stroke: currentcolor;
    stroke-width: 1.25;
    stroke-linecap: round;
    stroke-linejoin: round;
}

.copy-button.icon .check {
    color: var(--blue-text);
    stroke-width: 1.75;
}

.copy-button:hover:not(:disabled) {
    border-color: var(--blue-text);
}

.copy-button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.copy-button:disabled {
    color: var(--ink-muted);
    cursor: not-allowed;
}

.copy-button .done {
    color: var(--blue-text);
    font-size: 0.75rem;
    font-weight: 600;
}
</style>
