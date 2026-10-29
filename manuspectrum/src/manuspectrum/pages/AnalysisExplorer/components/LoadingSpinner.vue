<script setup lang="ts">
/** A rainbow ring for a short inline wait; decorative, the caller writes what is loading. */
const props = withDefaults(defineProps<{ size?: "small" | "medium" }>(), {
    size: "small",
});
</script>

<template>
    <span
        class="loading-spinner"
        aria-hidden="true"
        :class="`loading-spinner--${props.size}`"
    ></span>
</template>

<style scoped>
.loading-spinner {
    display: inline-block;
    flex: none;
    border-radius: 50%;
    background: conic-gradient(
        var(--spectral-1),
        var(--spectral-2),
        var(--spectral-3),
        var(--spectral-4),
        var(--spectral-5),
        var(--spectral-6),
        var(--spectral-1)
    );
    mask: radial-gradient(farthest-side, transparent 62%, var(--ink) 64%);
    animation: loading-spinner-turn 0.9s linear infinite;
    vertical-align: middle;
}

.loading-spinner--small {
    inline-size: 1rem;
    block-size: 1rem;
}

.loading-spinner--medium {
    inline-size: 1.75rem;
    block-size: 1.75rem;
}

@keyframes loading-spinner-turn {
    to {
        transform: rotate(1turn);
    }
}

@media (prefers-reduced-motion: reduce) {
    .loading-spinner {
        animation: none;
    }
}
</style>
