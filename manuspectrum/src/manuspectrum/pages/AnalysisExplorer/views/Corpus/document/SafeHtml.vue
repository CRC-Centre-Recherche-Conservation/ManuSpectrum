<script setup lang="ts">
import DOMPurify from "dompurify";
import { computed } from "vue";

// Same allow-list as the server's nh3 cleaning (spec §3.2); the browser cleans again.
const ALLOWED_TAGS = [
    "p",
    "br",
    "em",
    "strong",
    "ul",
    "ol",
    "li",
    "sub",
    "sup",
];

const props = defineProps<{ html: string; lang: string }>();

const clean = computed(() =>
    DOMPurify.sanitize(props.html, { ALLOWED_TAGS, ALLOWED_ATTR: [] }),
);
</script>

<template>
    <div
        class="safe-html"
        :lang="props.lang || undefined"
    >
        <!-- eslint-disable-next-line vue/no-v-html -- DOMPurify output, allow-list above -->
        <div v-html="clean"></div>
    </div>
</template>

<style scoped>
.safe-html :deep(p + p) {
    margin-block-start: 0.5rem;
}

.safe-html :deep(ul),
.safe-html :deep(ol) {
    padding-inline-start: 1.25rem;
}
</style>
