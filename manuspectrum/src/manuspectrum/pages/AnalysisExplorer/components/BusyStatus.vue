<script setup lang="ts">
import { useGettext } from "vue3-gettext";

/**
 * A polite status line, hidden from sight, that says a region is loading
 * (`first`: nothing shown yet) or updating; empty when nothing loads.
 */
const props = withDefaults(defineProps<{ busy: boolean; first?: boolean }>(), {
    first: false,
});

const { $gettext } = useGettext();
</script>

<template>
    <p
        class="busy-status"
        role="status"
    >
        <span v-if="props.busy && props.first">{{ $gettext("Loading…") }}</span>
        <span v-else-if="props.busy">{{ $gettext("Updating…") }}</span>
    </p>
</template>

<style scoped>
.busy-status {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
</style>
