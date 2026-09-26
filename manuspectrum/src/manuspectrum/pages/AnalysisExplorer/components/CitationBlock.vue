<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import CopyButton from "@/manuspectrum/pages/AnalysisExplorer/components/CopyButton.vue";

import type { Citation } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const JSON_INDENT = 2;

/** One citation: its recommended text, as plain text, and a copy button per form (text, BibTeX, RIS, CSL-JSON, availability statement). */
const props = defineProps<{ citation: Citation }>();

const { $gettext } = useGettext();

const cslJson = computed(() =>
    JSON.stringify(props.citation.csl, null, JSON_INDENT),
);
</script>

<template>
    <div class="citation-block">
        <p class="recommended">{{ props.citation.recommended }}</p>
        <div class="copies">
            <CopyButton
                :text="props.citation.recommended"
                :label="$gettext('Copy the citation')"
            />
            <CopyButton
                :text="props.citation.bibtex"
                :label="$gettext('Copy BibTeX')"
            />
            <CopyButton
                :text="props.citation.ris"
                :label="$gettext('Copy RIS')"
            />
            <CopyButton
                :text="cslJson"
                :label="$gettext('Copy CSL-JSON')"
            />
            <CopyButton
                :text="props.citation.availability"
                :label="$gettext('Copy the data availability statement')"
            />
        </div>
    </div>
</template>

<style scoped>
.citation-block {
    display: grid;
    gap: 0.5rem;
}

.citation-block .recommended {
    padding-block: 0.5rem;
    padding-inline: 0.75rem;
    border-inline-start: 0.1875rem solid var(--border-hover);
    background: var(--bg-alt);
    font-size: 0.8125rem;
    line-height: 1.5;
    overflow-wrap: anywhere;
    user-select: all;
}

.citation-block .copies {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
}

.citation-block .copy-button {
    padding-inline: 0.625rem;
    font-size: 0.75rem;
}
</style>
