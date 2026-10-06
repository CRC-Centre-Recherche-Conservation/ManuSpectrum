<script setup lang="ts">
/**
 * A labelled on/off switch (`role="switch"`, `aria-checked`): a track with a
 * knob, then the text of the default slot, which names it. Other attributes
 * (`data-action`, `title`…) go to the button. A disabled switch stays
 * focusable (`aria-disabled`); the owner ignores its toggle.
 */
defineOptions({ inheritAttrs: false });

const props = defineProps<{
    checked: boolean;
    disabled?: boolean;
}>();

const emit = defineEmits<{ (event: "toggle"): void }>();
</script>

<template>
    <button
        v-bind="$attrs"
        type="button"
        class="switch-button"
        role="switch"
        :aria-checked="props.checked ? 'true' : 'false'"
        :aria-disabled="props.disabled ? 'true' : undefined"
        @click="emit('toggle')"
    >
        <span
            class="track"
            aria-hidden="true"
        >
            <span class="knob"></span>
        </span>
        <span class="text"><slot></slot></span>
    </button>
</template>

<style scoped>
.switch-button {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2rem);
    padding: 0;
    border: none;
    background: none;
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
    user-select: none;
}

.switch-button .track {
    position: relative;
    flex: none;
    inline-size: 1.875rem;
    block-size: 1.0625rem;
    border-radius: 999rem;
    background: var(--ink-dim);
}

.switch-button .knob {
    position: absolute;
    inset-block-start: 0.125rem;
    inset-inline-start: 0.125rem;
    inline-size: 0.8125rem;
    block-size: 0.8125rem;
    border-radius: 50%;
    background: var(--surface);
    box-shadow: 0 0.0625rem 0.125rem rgb(0 0 0 / 25%);
}

.switch-button[aria-checked="true"] .track {
    background: var(--accent);
}

.switch-button[aria-checked="true"] .knob {
    inset-inline-start: 0.9375rem;
}

.switch-button[aria-disabled="true"] {
    opacity: 0.5;
    cursor: default;
}

.switch-button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

@media (prefers-reduced-motion: no-preference) {
    .switch-button .track {
        transition: background-color 0.15s ease-out;
    }

    .switch-button .knob {
        transition: inset-inline-start 0.15s ease-out;
    }
}

@media (forced-colors: active) {
    .switch-button .track {
        border: 0.0625rem solid ButtonText;
    }

    .switch-button[aria-checked="true"] .track {
        background: Highlight;
    }
}
</style>
