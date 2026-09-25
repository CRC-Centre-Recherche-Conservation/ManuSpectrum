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
                  "%{n} draft in this document; it is marked “Draft”.",
                  "%{n} drafts in this document; they are marked “Draft”.",
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
    padding: 0.375rem 0.75rem;
    border-inline-start: 0.1875rem solid var(--accent);
    border-radius: 0.25rem;
    background: var(--bg-warm);
    color: var(--ink);
    font-size: 0.8125rem;
}
</style>
