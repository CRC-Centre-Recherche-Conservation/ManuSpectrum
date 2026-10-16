<script setup lang="ts">
import CorpusDocument from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusDocument.vue";
import CorpusHome from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusHome.vue";
import CorpusResults from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusResults.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

const store = useExplorerStore();
</script>

<template>
    <CorpusDocument
        v-if="store.corpusScreen === 'document' && store.document"
        :document-id="store.document.id"
    />
    <CorpusResults v-else-if="store.corpusScreen === 'results'" />
    <CorpusHome v-else />
</template>
