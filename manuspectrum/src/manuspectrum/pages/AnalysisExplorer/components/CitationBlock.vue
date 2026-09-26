<script setup lang="ts">
import { computed, ref } from "vue";
import Tab from "primevue/tab";
import TabList from "primevue/tablist";
import TabPanel from "primevue/tabpanel";
import TabPanels from "primevue/tabpanels";
import Tabs from "primevue/tabs";
import { useGettext } from "vue3-gettext";

import CopyButton from "@/manuspectrum/pages/AnalysisExplorer/components/CopyButton.vue";

import type { Citation } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const TEXT = "text";
const BIBTEX = "bibtex";

/**
 * One citation in the manner of a code forge's « Cite this repository »:
 * a Text tab (the recommended citation, as plain text) and a BibTeX tab,
 * with one icon button copying the form shown.
 */
const props = defineProps<{ citation: Citation }>();

const { $gettext } = useGettext();

const form = ref<string | number>(TEXT);

const copied = computed(() =>
    form.value === BIBTEX ? props.citation.bibtex : props.citation.text,
);
const copyLabel = computed(() =>
    form.value === BIBTEX
        ? $gettext("Copy BibTeX")
        : $gettext("Copy the citation"),
);
</script>

<template>
    <div class="citation-block">
        <Tabs v-model:value="form">
            <div class="bar">
                <TabList>
                    <Tab :value="TEXT">
                        <span>{{ $gettext("Text") }}</span>
                    </Tab>
                    <Tab :value="BIBTEX">
                        <span>{{ $gettext("BibTeX") }}</span>
                    </Tab>
                </TabList>
                <CopyButton
                    :text="copied"
                    :label="copyLabel"
                    :icon-only="true"
                />
            </div>
            <TabPanels>
                <TabPanel :value="TEXT">
                    <p class="text">{{ props.citation.text }}</p>
                </TabPanel>
                <TabPanel :value="BIBTEX">
                    <pre class="bibtex">{{ props.citation.bibtex.trim() }}</pre>
                </TabPanel>
            </TabPanels>
        </Tabs>
    </div>
</template>

<style scoped>
.citation-block {
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
}

.citation-block .bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding-inline-end: 0.25rem;
    border-block-end: 0.0625rem solid var(--border-hover);
}

.citation-block .bar :deep(.p-tablist) {
    flex: 1;
    min-inline-size: 0;
}

.citation-block .bar :deep(.p-tablist-tab-list) {
    border-block-end: none;
    background: transparent;
}

.citation-block .bar :deep(.p-tab) {
    padding-block: 0.5rem;
    padding-inline: 0.75rem;
    font-size: 0.8125rem;
}

.citation-block .bar .copy-button {
    --explorer-target: 2.25rem;
}

.citation-block :deep(.p-tabpanels) {
    padding: 0;
    background: transparent;
}

.citation-block .text,
.citation-block .bibtex {
    margin: 0;
    padding-block: 0.625rem;
    padding-inline: 0.75rem;
    font-size: 0.8125rem;
    line-height: 1.5;
    overflow-wrap: anywhere;
    user-select: all;
}

.citation-block .bibtex {
    max-block-size: 12rem;
    overflow: auto;
    background: var(--bg-alt);
    font-family: ui-monospace, monospace;
    font-size: 0.75rem;
    white-space: pre-wrap;
}
</style>
