<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import { safeHref } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";

import type {
    AnalysisPayload,
    FileEntry,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const props = defineProps<{ file: FileEntry; analysis: AnalysisPayload }>();

const { $gettext, interpolate } = useGettext();

const href = computed(() => safeHref(props.file.downloadUrl));
const downloadLabel = computed(() =>
    interpolate($gettext("Download %{name}"), { name: props.file.name }, true),
);
</script>

<template>
    <p class="file-only">
        <span>{{
            $gettext("Not in a chart: this file can be downloaded.")
        }}</span>
        <a
            v-if="href"
            class="download"
            download=""
            :href="href"
        >
            <span>{{ downloadLabel }}</span>
        </a>
    </p>
</template>

<style scoped>
.file-only {
    display: grid;
    gap: 0.5rem;
    color: var(--ink-muted);
}

.file-only .download {
    color: var(--blue-text);
    min-block-size: var(--explorer-target, 2.75rem);
    display: inline-flex;
    align-items: center;
}
</style>
