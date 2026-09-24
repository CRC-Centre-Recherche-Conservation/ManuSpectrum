<script setup lang="ts">
import { useGettext } from "vue3-gettext";

const props = defineProps<{ status: "unavailable" | "error" }>();
const emit = defineEmits<{ retry: []; home: [] }>();

const { $gettext } = useGettext();

function retry(): void {
    emit("retry");
}

function goHome(): void {
    emit("home");
}
</script>

<template>
    <div
        class="unavailable-state"
        role="status"
    >
        <p
            v-if="props.status === 'unavailable'"
            class="message"
        >
            <span>
                {{
                    $gettext(
                        "This item is not available. It may not exist, or it may not be public.",
                    )
                }}
            </span>
        </p>
        <p
            v-else
            class="message"
        >
            <span>{{
                $gettext("The service is not answering right now.")
            }}</span>
        </p>
        <button
            v-if="props.status === 'error'"
            type="button"
            class="retry"
            @click="retry"
        >
            <span>{{ $gettext("Retry") }}</span>
        </button>
        <button
            v-else
            type="button"
            class="home"
            @click="goHome"
        >
            <span>{{ $gettext("Back to the explorer home") }}</span>
        </button>
    </div>
</template>

<style scoped>
.unavailable-state {
    display: grid;
    justify-items: start;
    gap: 1rem;
    padding: 2rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.75rem;
    background: var(--surface);
}

.unavailable-state .message {
    color: var(--ink);
}

.unavailable-state .retry,
.unavailable-state .home {
    min-block-size: 2.75rem;
    padding-inline: 1.25rem;
    border: 0.0625rem solid var(--ink);
    border-radius: 999rem;
    background: var(--ink);
    color: var(--surface);
    font: inherit;
    cursor: pointer;
}

.unavailable-state .retry:focus-visible,
.unavailable-state .home:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
