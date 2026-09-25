<script setup lang="ts">
import { onBeforeUnmount, onMounted, useTemplateRef } from "vue";

import { viewerFor } from "@/manuspectrum/pages/AnalysisExplorer/viewers/registry.ts";

import type {
    AnalysisPayload,
    FileEntry,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { ExternalHandle } from "@/manuspectrum/pages/AnalysisExplorer/viewers/registry.ts";

const props = defineProps<{ file: FileEntry; analysis: AnalysisPayload }>();
const emit = defineEmits<{ event: [name: string, detail?: unknown] }>();

const host = useTemplateRef<HTMLDivElement>("host");
let handle: ExternalHandle | null = null;

onMounted(() => {
    const mount = viewerFor(props.file.dataKind).external;
    if (host.value && mount) {
        handle = mount(host.value, {
            file: props.file,
            analysis: props.analysis,
            language: document.documentElement.lang,
            onEvent: (name, detail) => emit("event", name, detail),
        });
    }
});

onBeforeUnmount(() => {
    handle?.destroy();
    handle = null;
});
</script>

<template>
    <div
        ref="host"
        class="external-viewer"
    ></div>
</template>

<style scoped>
.external-viewer {
    min-block-size: 16rem;
}
</style>
