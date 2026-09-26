<script setup lang="ts">
import { inject } from "vue";
import { useClipboard } from "@vueuse/core";
import { useGettext } from "vue3-gettext";

import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

/**
 * A button that copies `text` to the clipboard (the Clipboard API, else the
 * browser's copy command), says « Copied » on itself for a moment and through
 * the shell's live region. Disabled while `text` is empty.
 */
const props = defineProps<{ text: string; label: string }>();

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
