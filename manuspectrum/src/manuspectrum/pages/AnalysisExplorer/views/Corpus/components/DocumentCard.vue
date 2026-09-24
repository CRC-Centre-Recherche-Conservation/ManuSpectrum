<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import type { DocumentHit } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const props = defineProps<{ hit: DocumentHit; href: string }>();
const emit = defineEmits<{ open: [id: string] }>();

const { $gettext, $ngettext, interpolate } = useGettext();

const countText = computed(() =>
    interpolate(
        $ngettext("%{n} analysis", "%{n} analyses", props.hit.analysisCount),
        {
            n: props.hit.analysisCount,
        },
    ),
);

function open(event: MouseEvent): void {
    if (
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.button !== 0
    ) {
        return;
    }
    event.preventDefault();
    emit("open", props.hit.id);
}
</script>

<template>
    <article class="document-card">
        <img
            v-if="props.hit.thumbnail"
            class="thumbnail"
            alt=""
            loading="lazy"
            :src="props.hit.thumbnail"
        />
        <div class="body">
            <h3 class="name">
                <a
                    class="link"
                    :href="props.href"
                    :lang="props.hit.name.lang"
                    @click="open"
                    >{{ props.hit.name.value }}</a
                >
            </h3>
            <p class="meta">
                <span>{{ countText }}</span>
                <span
                    v-if="props.hit.unpublished"
                    class="badge"
                    >{{ $gettext("Draft") }}</span
                >
            </p>
        </div>
    </article>
</template>

<style scoped>
.document-card {
    display: grid;
    grid-template-columns: 5rem 1fr;
    gap: 1rem;
    padding: 1rem;
    border: 0.0625rem solid var(--border);
    border-radius: 0.75rem;
    background: var(--surface);
}

.document-card .thumbnail {
    inline-size: 5rem;
    block-size: 6.5rem;
    object-fit: cover;
    border-radius: 0.375rem;
    background: var(--bg-alt);
}

.document-card .name {
    font-family: var(--font-display);
    font-size: 1.25rem;
    font-weight: 500;
}

.document-card .link {
    color: var(--ink);
}

.document-card .link:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.document-card .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    color: var(--ink-muted);
    font-size: 0.875rem;
}

.document-card .badge {
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--accent-text);
    border-radius: 999rem;
    color: var(--accent-text);
    font-size: 0.75rem;
}
</style>
