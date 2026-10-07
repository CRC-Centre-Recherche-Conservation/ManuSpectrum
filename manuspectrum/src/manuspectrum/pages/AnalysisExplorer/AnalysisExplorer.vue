<script setup lang="ts">
import {
    computed,
    effectScope,
    nextTick,
    onBeforeUnmount,
    onMounted,
    provide,
    ref,
    shallowRef,
    watch,
} from "vue";
import { useGettext } from "vue3-gettext";

import ActiveFiltersBar from "@/manuspectrum/pages/AnalysisExplorer/components/ActiveFiltersBar.vue";
import LoadingSpinner from "@/manuspectrum/pages/AnalysisExplorer/components/LoadingSpinner.vue";
import SelectionDrawer from "@/manuspectrum/pages/AnalysisExplorer/components/SelectionDrawer.vue";
import ShareExportPanel from "@/manuspectrum/pages/AnalysisExplorer/components/ShareExportPanel.vue";
import SharedSelectionPrompt from "@/manuspectrum/pages/AnalysisExplorer/components/SharedSelectionPrompt.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import ViewTabs from "@/manuspectrum/pages/AnalysisExplorer/components/ViewTabs.vue";
import CorpusView from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusView.vue";

import { useUrlState } from "@/manuspectrum/public/useUrlState.ts";
import { useSelectionItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionItems.ts";
import {
    ANNOUNCE_KEY,
    CITE_OPEN_KEY,
    FACET_LABELS_KEY,
    MIRADOR_URL_KEY,
    RESULTS_MEMO_KEY,
    SCREEN_FOCUS_KEY,
    SELECTION_HINTS_KEY,
    SELECTION_ITEMS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    INTRO_BAR_ID,
    introBar,
} from "@/manuspectrum/pages/AnalysisExplorer/intro-bar.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { loadCompareView } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/load-compare-view.ts";
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

import type { Component } from "vue";

import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { SelectionItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionItems.ts";
import type {
    ResultsMemo,
    SelectionHint,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import type { SharedSelection } from "@/manuspectrum/pages/AnalysisExplorer/store/selection-link.ts";

// Read before useUrlState rewrites the URL without `sel`.
const INITIAL_SELECTION = parseSelection(
    new URLSearchParams(window.location.search).get(SELECTION_PARAM),
);

/** `miradorUrl`: the viewer of `EXPLORER_MIRADOR_URL`, empty when none is set. */
const props = withDefaults(defineProps<{ miradorUrl?: string }>(), {
    miradorUrl: "",
});

const store = useExplorerStore();
const { $gettext } = useGettext();

/** The stored Selection was emptied for age (on this load or by another tab); the notice stays until dismissed. */
const { expired: selectionExpired } = useBasketPersistence(store);
useUrlState({
    snapshot: () => snapshotOf(store),
    toQuery,
    apply: (query) => applySnapshot(store, fromQuery(query)),
    historyMode,
});

const hasIntroBar = introBar() !== null;
const sharedSelection = ref<SharedSelection | null>(INITIAL_SELECTION);
const announcement = ref("");
const facetLabels = ref(new Map<string, Label>());
const screenFocusPending = ref(false);
const resultsMemo = ref<ResultsMemo | null>(null);
const selectionHints = ref(new Map<string, SelectionHint>());
/** Whether the « Cite » block of the Analysis card is unfolded: memory only, for the life of the tab. */
const citeOpen = ref(false);
/** The Compare view once its chunk has arrived. */
const compareView = shallowRef<Component>();
/** Its chunk is on its way, or could not be fetched (Retry fetches it again). */
const compareChunk = ref<"idle" | "loading" | "failed">("idle");
/** The shared reading of the Selection, started by its first reader (the Selection panel or the Compare view). */
const selectionScope = effectScope();
let selectionItems: SelectionItems | null = null;

/** The screen shown, as CorpusView decides it: the page intro folds to one line off the home. */
const screen = computed(() => {
    if (store.view !== "corpus") return store.view;
    if (store.corpusScreen === "document" && store.document) return "document";
    return store.corpusScreen === "results" ? "results" : "home";
});

provide(FACET_LABELS_KEY, facetLabels);
provide(SCREEN_FOCUS_KEY, screenFocusPending);
provide(RESULTS_MEMO_KEY, resultsMemo);
provide(SELECTION_HINTS_KEY, selectionHints);
provide(ANNOUNCE_KEY, announce);
provide(MIRADOR_URL_KEY, props.miradorUrl);
provide(CITE_OPEN_KEY, citeOpen);
provide(SELECTION_ITEMS_KEY, sharedSelectionItems);

/**
 * Another view, a new Corpus screen or another document moves the focus to
 * the heading shown next, whether the reader or the history changed it; the
 * screen the address opens on first render keeps the page's focus, and the
 * same document named again by the address is no change.
 */
watch(
    () => `${store.view}:${store.corpusScreen}:${store.document?.id ?? ""}`,
    () => {
        screenFocusPending.value = true;
    },
);

watch(
    () => store.view,
    (view) => {
        if (view === "compare") void openCompare();
    },
    { immediate: true },
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

function sharedSelectionItems(): SelectionItems {
    selectionItems ??=
        selectionScope.run(useSelectionItems) ?? useSelectionItems();
    return selectionItems;
}

/** Clearing the region first makes a repeated message spoken again. */
function announce(message: string): void {
    announcement.value = "";
    void nextTick(() => {
        announcement.value = message;
    });
}

function announceExpiry(): void {
    announce(
        $gettext(
            "Your Selection, unchanged for more than 90 days, has been emptied.",
        ),
    );
}

onMounted(() => {
    if (selectionExpired.value) announceExpiry();
});

watch(selectionExpired, (expired) => {
    if (expired) announceExpiry();
});

/** Fetches the Compare view's chunk, once; a failure is shown with Retry. */
async function openCompare(): Promise<void> {
    if (compareView.value || compareChunk.value === "loading") return;
    compareChunk.value = "loading";
    try {
        compareView.value = await loadCompareView();
        compareChunk.value = "idle";
    } catch (error: unknown) {
        compareChunk.value = "failed";
        console.error("The Compare view could not be loaded", error);
    }
}

function onSelectionResolved(message: string): void {
    sharedSelection.value = null;
    announcement.value = message;
    screenFocusPending.value = true;
}
</script>

<template>
    <div class="analysis-explorer">
        <Teleport
            :to="`#${INTRO_BAR_ID}`"
            :disabled="!hasIntroBar"
        >
            <ShareExportPanel class="share" />
            <SelectionDrawer class="selection" />
        </Teleport>
        <p
            v-if="selectionExpired"
            class="selection-expired"
        >
            <span>{{
                $gettext(
                    "Your Selection, unchanged for more than 90 days, has been emptied.",
                )
            }}</span>
            <button
                type="button"
                @click="selectionExpired = false"
            >
                <span>{{ $gettext("Close") }}</span>
            </button>
        </p>
        <ViewTabs />
        <SharedSelectionPrompt
            v-if="sharedSelection"
            :selection="sharedSelection"
            @resolved="onSelectionResolved"
        />
        <ActiveFiltersBar v-if="store.view !== 'compare'" />
        <CorpusView v-if="store.view === 'corpus'" />
        <template v-else-if="store.view === 'compare'">
            <component
                :is="compareView"
                v-if="compareView"
            />
            <UnavailableState
                v-else-if="compareChunk === 'failed'"
                status="error"
                :hide-home="true"
                @retry="openCompare"
            />
            <p
                v-else
                class="compare-loading"
                role="status"
            >
                <LoadingSpinner />
                <span>{{ $gettext("Loading the Compare view…") }}</span>
            </p>
        </template>
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

.analysis-explorer .selection-expired {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin: 0;
    color: var(--ink-muted);
    font-size: 0.875rem;
}

.analysis-explorer .selection-expired button {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0;
    background: none;
    color: inherit;
    text-decoration: underline;
    cursor: pointer;
}

.analysis-explorer .compare-loading {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0;
    color: var(--ink-muted);
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
