<script setup lang="ts">
import { computed } from "vue";
import SelectButton from "primevue/selectbutton";
import { useGettext } from "vue3-gettext";

import type { FolioView } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const props = defineProps<{
    view: FolioView;
    available: FolioView[];
}>();

const emit = defineEmits<{ change: [view: FolioView] }>();

const { $gettext } = useGettext();

const options = computed(() => {
    const labels: Record<FolioView, string> = {
        analyses: $gettext("Analyses"),
        characterizations: $gettext("Identified materials"),
        samples: $gettext("Samples"),
    };
    return props.available.map((value) => ({ value, label: labels[value] }));
});

/** A single choice: pressing the current view again keeps it. */
function choose(next: FolioView | null): void {
    if (next && next !== props.view) emit("change", next);
}
</script>

<template>
    <div
        v-if="props.available.length > 1"
        class="folio-view-switch"
    >
        <span
            class="label"
            aria-hidden="true"
        >
            {{ $gettext("Show") }}
        </span>
        <SelectButton
            :model-value="props.view"
            :options="options"
            option-label="label"
            option-value="value"
            :allow-empty="false"
            :aria-label="$gettext('Show')"
            @update:model-value="choose"
        />
    </div>
</template>

<style scoped>
.folio-view-switch {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 0.75rem;
}

.folio-view-switch .label {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.folio-view-switch :deep(.p-togglebutton) {
    min-block-size: var(--explorer-target, 2.75rem);
    font-size: 0.8125rem;
}
</style>
