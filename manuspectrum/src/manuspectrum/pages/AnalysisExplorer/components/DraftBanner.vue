<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

const props = defineProps<{ count: number }>();

const { $ngettext, interpolate } = useGettext();

const message = computed(() =>
    interpolate(
        $ngettext(
            "%{n} draft on this page; it is marked “Draft”.",
            "%{n} drafts on this page; they are marked “Draft”.",
            props.count,
        ),
        { n: props.count },
    ),
);
</script>

<template>
    <p
        v-if="props.count > 0"
        class="draft-banner"
    >
        <span>{{ message }}</span>
    </p>
</template>

<style scoped>
.draft-banner {
    padding: 0.75rem 1rem;
    border-inline-start: 0.25rem solid var(--accent);
    background: var(--bg-warm);
    color: var(--ink);
    font-size: 0.875rem;
}
</style>
