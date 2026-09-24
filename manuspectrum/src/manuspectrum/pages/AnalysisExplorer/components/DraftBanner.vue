<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

const props = withDefaults(
    defineProps<{
        count: number;
        /** `results`: the count covers a whole search result set; `page`: the displayed document. */
        scope?: "page" | "results";
    }>(),
    { scope: "page" },
);

const { $ngettext, interpolate } = useGettext();

const message = computed(() => {
    const text =
        props.scope === "results"
            ? $ngettext(
                  "%{n} draft in these results; it is marked “Draft”.",
                  "%{n} drafts in these results; they are marked “Draft”.",
                  props.count,
              )
            : $ngettext(
                  "%{n} draft on this page; it is marked “Draft”.",
                  "%{n} drafts on this page; they are marked “Draft”.",
                  props.count,
              );
    return interpolate(text, { n: props.count }, true);
});
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
