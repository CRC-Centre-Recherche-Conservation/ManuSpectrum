<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

const props = withDefaults(
    defineProps<{
        count: number;
        /** `results`: the count covers a whole search result set; `page`: the displayed document; `tools`: what the Compare tools read. */
        scope?: "page" | "results" | "tools";
    }>(),
    { scope: "page" },
);

const { $ngettext, interpolate } = useGettext();

const message = computed(() => interpolate(text(), { n: props.count }, true));

function text(): string {
    switch (props.scope) {
        case "results":
            return $ngettext(
                "%{n} draft in these results; it is marked “Draft”.",
                "%{n} drafts in these results; they are marked “Draft”.",
                props.count,
            );
        case "tools":
            return $ngettext(
                "The tools read %{n} draft, not published yet.",
                "The tools read %{n} drafts, not published yet.",
                props.count,
            );
        default:
            return $ngettext(
                "%{n} draft in this document; it is marked “Draft”.",
                "%{n} drafts in this document; they are marked “Draft”.",
                props.count,
            );
    }
}
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
