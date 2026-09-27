<script setup lang="ts">
import MaterialsTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/MaterialsTable.vue";
import MicroImageGrid from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/MicroImageGrid.vue";
import NotInChartList from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/NotInChartList.vue";
import XyWorkshop from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/XyWorkshop.vue";

import type { AutoWindow } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/** The content of a window arranged from the Selection, by its kind. */
const props = defineProps<{ window: AutoWindow }>();
</script>

<template>
    <XyWorkshop
        v-if="props.window.kind === 'xy'"
        :curves="props.window.curves"
    />
    <MicroImageGrid
        v-else-if="props.window.kind === 'micro'"
        :images="props.window.images"
    />
    <MaterialsTable
        v-else-if="props.window.kind === 'characterizations'"
        :rows="props.window.rows"
    />
    <NotInChartList
        v-else
        :entries="props.window.entries"
    />
</template>
