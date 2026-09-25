<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, provide, ref, watch } from "vue";

import ActiveFiltersBar from "@/manuspectrum/pages/AnalysisExplorer/components/ActiveFiltersBar.vue";
import SharedSelectionPrompt from "@/manuspectrum/pages/AnalysisExplorer/components/SharedSelectionPrompt.vue";
import ViewTabs from "@/manuspectrum/pages/AnalysisExplorer/components/ViewTabs.vue";
import CorpusView from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusView.vue";

import { useUrlState } from "@/manuspectrum/public/useUrlState.ts";
import {
    ANNOUNCE_KEY,
    FACET_LABELS_KEY,
    SCREEN_FOCUS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { useBasketPersistence } from "@/manuspectrum/pages/AnalysisExplorer/store/persistence.ts";
import {
    SELECTION_PARAM,
    parseSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/store/selection-link.ts";
import {
    applySnapshot,
    fromQuery,
    historyMode,
    snapshotOf,
    toQuery,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";

import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { SharedSelection } from "@/manuspectrum/pages/AnalysisExplorer/store/selection-link.ts";

// Read before useUrlState rewrites the URL without `sel`.
const INITIAL_SELECTION = parseSelection(
    new URLSearchParams(window.location.search).get(SELECTION_PARAM),
);

const props = defineProps<{ connected: boolean }>();

const store = useExplorerStore();

store.$patch((state) => {
    state.session.connected = props.connected;
});
useBasketPersistence(store);
useUrlState({
    snapshot: () => snapshotOf(store),
    toQuery,
    apply: (query) => applySnapshot(store, fromQuery(query)),
    historyMode,
});

const sharedSelection = ref<SharedSelection | null>(INITIAL_SELECTION);
const announcement = ref("");
const facetLabels = ref(new Map<string, Label>());
const screenFocusPending = ref(false);

/** The screen shown, as CorpusView decides it: the page intro folds to one line off the home. */
const screen = computed(() => {
    if (store.view !== "corpus") return store.view;
    if (store.corpusScreen === "document" && store.document) return "document";
    return store.corpusScreen === "results" ? "results" : "home";
});

provide(FACET_LABELS_KEY, facetLabels);
provide(SCREEN_FOCUS_KEY, screenFocusPending);
provide(ANNOUNCE_KEY, announce);

/** A new screen or another document; the same document named again by the address is neither. */
watch(
    () => `${store.corpusScreen}:${store.document?.id ?? ""}`,
    () => {
        screenFocusPending.value = true;
    },
);

watch(
    screen,
    (name) => {
        window.document.body.dataset.explorerScreen = name;
    },
    { immediate: true },
);

onBeforeUnmount(() => {
    delete window.document.body.dataset.explorerScreen;
});

/** Clearing the region first makes a repeated message spoken again. */
function announce(message: string): void {
    announcement.value = "";
    void nextTick(() => {
        announcement.value = message;
    });
}

function onSelectionResolved(message: string): void {
    sharedSelection.value = null;
    announcement.value = message;
    screenFocusPending.value = true;
}
</script>

<template>
    <div class="analysis-explorer">
        <ViewTabs />
        <SharedSelectionPrompt
            v-if="sharedSelection"
            :selection="sharedSelection"
            @resolved="onSelectionResolved"
        />
        <ActiveFiltersBar />
        <CorpusView v-if="store.view === 'corpus'" />
        <p
            class="announcer"
            aria-live="polite"
        >
            <span>{{ announcement }}</span>
        </p>
    </div>
</template>

<style scoped>
.analysis-explorer {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.5rem;
}

.analysis-explorer .announcer {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

@media (prefers-reduced-motion: reduce) {
    .analysis-explorer * {
        transition: none;
        animation: none;
    }
}
</style>
