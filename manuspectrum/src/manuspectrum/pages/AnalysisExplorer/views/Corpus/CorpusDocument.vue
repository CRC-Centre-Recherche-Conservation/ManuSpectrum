<script setup lang="ts">
import {
    computed,
    inject,
    nextTick,
    provide,
    ref,
    useTemplateRef,
    watch,
} from "vue";
import { useMediaQuery } from "@vueuse/core";
import Drawer from "primevue/drawer";
import { useGettext } from "vue3-gettext";

import BusyStatus from "@/manuspectrum/pages/AnalysisExplorer/components/BusyStatus.vue";
import DraftBanner from "@/manuspectrum/pages/AnalysisExplorer/components/DraftBanner.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import FacetRail from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetRail.vue";
import RailPanel from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/RailPanel.vue";
import AnalysisCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/AnalysisCard.vue";
import CanvasStrip from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/CanvasStrip.vue";
import CharacterizationCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/CharacterizationCard.vue";
import FolioLegend from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/FolioLegend.vue";
import FolioMap from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/FolioMap.vue";
import FolioViewSwitch from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/FolioViewSwitch.vue";
import OnThisPage from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/OnThisPage.vue";
import SampleCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/SampleCard.vue";
import SelectionPanel from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/SelectionPanel.vue";

import { searchOf } from "@/manuspectrum/public/useUrlState.ts";
import { useAnalysis } from "@/manuspectrum/pages/AnalysisExplorer/composables/useAnalysis.ts";
import { useDocument } from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocument.ts";
import { useFacetLabels } from "@/manuspectrum/pages/AnalysisExplorer/composables/useFacetLabels.ts";
import { useScreenHeading } from "@/manuspectrum/pages/AnalysisExplorer/composables/useScreenHeading.ts";
import {
    searchQuery,
    useSearch,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useSearch.ts";
import { shapeBounds } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import { characterizationMatches } from "@/manuspectrum/pages/AnalysisExplorer/folio/matching.ts";
import {
    firstMatchingPage,
    pageCounts,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/page-counts.ts";
import { folioOverlays } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import {
    techniqueKey,
    techniqueStyles,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import {
    CURTAIN_KEY,
    FOLIO_ZONES_KEY,
    RESULTS_MEMO_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    hasActiveFilters,
    PAGE_SIZES,
    selectedFacets,
    useExplorerStore,
} from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    snapshotOf,
    toQuery,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";

import type {
    DocumentCanvas,
    FacetKey,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    Focus,
    FolioView,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";
import type { PageCount } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-counts.ts";
import type { ResultsMemo } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import type { LegendEntry } from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/FolioLegend.vue";

const NARROW_QUERY = "(max-width: 48rem)";
const PHONE_QUERY = "(max-width: 30rem)";
const CARD_HEADING_ID = "explorer-card-heading";

const props = defineProps<{ documentId: string }>();

const store = useExplorerStore();
const { $gettext, $ngettext, interpolate } = useGettext();
const payload = useDocument(
    () => props.documentId,
    () => searchQuery(store.filters, 1),
);
const search = useSearch(() =>
    searchQuery({ ...store.filters, grain: "analyses" }, 1, {
        document: props.documentId,
        size: PAGE_SIZES[0],
    }),
);
const resultsMemo = inject(
    RESULTS_MEMO_KEY,
    () => ref<ResultsMemo | null>(null),
    true,
);
useFacetLabels(() => search.data.value?.facets);
const focusedAnalysis = computed(() =>
    store.focus?.kind === "analysis" ? store.focus.id : null,
);
const analysis = useAnalysis(() => focusedAnalysis.value);
const narrow = useMediaQuery(NARROW_QUERY);
const phone = useMediaQuery(PHONE_QUERY);
const heading = useTemplateRef<HTMLElement>("heading");
const backButton = useTemplateRef<HTMLElement>("back-button");
const folio = useTemplateRef<{
    focusTarget: (id: string) => void;
    focusCurrent: () => void;
}>("folio");
const card = useTemplateRef<{ focusHeading: () => void }>("card");
const rail = useTemplateRef<{ focusFilters: () => void }>("rail");
const side = useTemplateRef<HTMLElement>("side");

const curtain = ref<string | null>(null);
let pageToFollow = store.focus !== null;
/** The document whose first payload has placed the page. */
let landedOn: string | null = null;
let openedOver: string | null = null;
/** The `data-focus` of the list entry that opened the card, if a list entry did. */
let openedFrom: string | null = null;

const data = computed(() =>
    payload.data.value?.id === props.documentId ? payload.data.value : null,
);
const failed = computed(
    () =>
        payload.status.value === "error" ||
        payload.status.value === "unavailable",
);
/** S7 replaces the screen only when this document was never shown; a failed reload is reported inline. */
const isUnavailable = computed(() => failed.value && data.value === null);
const certaintyScale = computed(
    () => data.value?.certaintyScale ?? { levels: [] },
);
const canvases = computed(() => data.value?.canvases ?? []);
/** A result names a page by its canvas id or by its image service (as Arches annotations do). */
function isCanvas(
    canvas: DocumentCanvas,
    name: string | null | undefined,
): boolean {
    return (
        Boolean(name) &&
        (canvas.id === name ||
            canvas.image.service?.replace(/\/$/, "") ===
                name?.replace(/\/$/, ""))
    );
}

const perPage = computed(() =>
    data.value ? pageCounts(data.value) : new Map<string, PageCount>(),
);
const filtered = computed(() => hasActiveFilters(store.filters));
const currentCanvas = computed(
    () =>
        canvases.value.find((canvas) =>
            isCanvas(canvas, store.document?.canvas),
        ) ??
        canvases.value.find((canvas) => canvas.analysisCount > 0) ??
        canvases.value[0] ??
        null,
);
const pageAnnotations = computed(() =>
    (data.value?.annotations ?? []).filter(
        (entry) => entry.canvas === currentCanvas.value?.id,
    ),
);
const pageCharacterizations = computed(() =>
    (data.value?.characterizations ?? []).filter(
        (summary) => summary.zone?.canvas === currentCanvas.value?.id,
    ),
);
/** The identified materials drawn on this page and those without a zone. */
const listedCharacterizations = computed(() =>
    (data.value?.characterizations ?? []).filter(
        (summary) =>
            !summary.zone || summary.zone.canvas === currentCanvas.value?.id,
    ),
);
/** The samples drawn on this page. */
const pageSamples = computed(() =>
    (data.value?.samples ?? []).filter(
        (entry) => entry.zone?.canvas === currentCanvas.value?.id,
    ),
);
/** The samples drawn on this page and those without a zone. */
const listedSamples = computed(() =>
    (data.value?.samples ?? []).filter(
        (entry) => !entry.zone || entry.zone.canvas === currentCanvas.value?.id,
    ),
);
/** The folio views that have something on this page, in the order of the switch. */
const availableViews = computed(() => {
    const views: FolioView[] = [];
    if (
        pageAnnotations.value.length > 0 ||
        (data.value?.unlocated ?? []).length > 0
    )
        views.push("analyses");
    if (listedCharacterizations.value.length > 0)
        views.push("characterizations");
    if (listedSamples.value.length > 0) views.push("samples");
    return views;
});
/** The view the folio and the page list show: the one chosen, or the first this page has. */
const folioView = computed<FolioView>(() =>
    availableViews.value.includes(store.folioView)
        ? store.folioView
        : availableViews.value[0] ?? "analyses",
);
/** Names of the document's analyses, by id. */
const analysisNames = computed(
    () =>
        new Map<string, Label>(
            [
                ...(data.value?.annotations ?? []),
                ...(data.value?.unlocated ?? []),
            ].map((entry) => [entry.analysis, entry.name]),
        ),
);
const styles = computed(() =>
    techniqueStyles(
        [
            ...(data.value?.annotations ?? []).map((entry) => entry.technique),
            ...(data.value?.unlocated ?? []).map((entry) => entry.technique),
        ],
        { value: $gettext("Analysis"), lang: "" },
    ),
);
/** The techniques drawn on this page (in the analyses view, or lit as evidence), with their number of analyses. */
const pageLegend = computed<LegendEntry[]>(() => {
    const drawn =
        folioView.value === "analyses"
            ? pageAnnotations.value
            : pageAnnotations.value.filter(
                  (entry) => lit.value?.has(entry.analysis) ?? false,
              );
    const analyses = new Map<string, Set<string>>();
    for (const entry of drawn) {
        const key = techniqueKey(entry.technique);
        analyses.set(key, (analyses.get(key) ?? new Set()).add(entry.analysis));
    }
    return [...styles.value.values()]
        .filter((style) => analyses.has(style.key))
        .map((style) => ({
            key: style.key,
            code: style.code,
            colour: style.colour,
            label: style.label,
            count: analyses.get(style.key)!.size,
        }));
});
/** The Selection slots of each analysis or identified material, by id. */
const slots = computed(() => {
    const map = new Map<string, string[]>();
    for (const item of store.basket) {
        const id = item.key.split(":")[1];
        map.set(id, [...(map.get(id) ?? []), slotLabel(item.slot)]);
    }
    return map;
});
const openCharacterization = computed(() => {
    const focus = store.focus;
    if (focus?.kind !== "characterization") return null;
    return (
        data.value?.characterizations.find(
            (summary) => summary.id === focus.id,
        ) ?? null
    );
});
const openSample = computed(() => {
    const focus = store.focus;
    if (focus?.kind !== "sample") return null;
    return data.value?.samples.find((entry) => entry.id === focus.id) ?? null;
});
const cardOpen = computed(
    () =>
        focusedAnalysis.value !== null ||
        openCharacterization.value !== null ||
        openSample.value !== null,
);
const lit = computed(() =>
    openCharacterization.value
        ? new Set(openCharacterization.value.evidence)
        : null,
);
const dimmedMaterials = computed(
    () =>
        new Set(
            (data.value?.characterizations ?? [])
                .filter(
                    (summary) =>
                        !characterizationMatches(
                            summary,
                            store.filters,
                            search.data.value?.facets ?? [],
                        ),
                )
                .map((summary) => summary.id),
        ),
);
const zones = computed<ReadonlySet<string>>(
    () =>
        new Set(
            pageAnnotations.value
                .filter((entry) => shapeBounds(entry.shape) !== null)
                .map((entry) => entry.analysis),
        ),
);
const overlays = computed(() =>
    folioOverlays(
        analysis.data.value?.id === focusedAnalysis.value
            ? analysis.data.value
            : null,
        store.overlays,
        pageAnnotations.value,
    ),
);
const pageCount = computed(() => {
    const matches = new Map(
        pageAnnotations.value.map((entry) => [entry.analysis, entry.match]),
    );
    const total = matches.size;
    return interpolate(
        $ngettext(
            "%{n} / %{total} analysis on this page",
            "%{n} / %{total} analyses on this page",
            total,
        ),
        { n: [...matches.values()].filter(Boolean).length, total },
        true,
    );
});
const counts = computed(() => {
    const analyses = new Set([
        ...(data.value?.annotations ?? []).map((entry) => entry.analysis),
        ...(data.value?.unlocated ?? []).map((entry) => entry.analysis),
    ]).size;
    const materials = data.value?.characterizations.length ?? 0;
    return [
        interpolate(
            $ngettext("%{n} analysis", "%{n} analyses", analyses),
            { n: analyses },
            true,
        ),
        interpolate(
            $ngettext(
                "%{n} identified material",
                "%{n} identified materials",
                materials,
            ),
            { n: materials },
            true,
        ),
    ].join(" · ");
});
/** The label of the button that closes the filter drawer: the document's analyses the filters keep. */
const showLabel = computed(() => {
    const kept = new Set(
        [...(data.value?.annotations ?? []), ...(data.value?.unlocated ?? [])]
            .filter((entry) => entry.match)
            .map((entry) => entry.analysis),
    ).size;
    return interpolate(
        $ngettext("See %{n} analysis", "See %{n} analyses", kept),
        { n: kept },
        true,
    );
});
/** The line under the page: document, page label, position among the pages. */
const folioCaption = computed(() => {
    const canvas = currentCanvas.value;
    if (!data.value || !canvas) return "";
    const position = interpolate(
        $gettext("page %{n} / %{total}"),
        {
            n: canvases.value.indexOf(canvas) + 1,
            total: canvases.value.length,
        },
        true,
    );
    return [data.value.name.value, canvas.label, position].join(" · ");
});
/** « Results », with their number when the results left are known. */
const backLabel = computed(() => {
    if (store.documentOrigin !== "results") {
        return $gettext("Back to the explorer home");
    }
    const payload = resultsMemo.value?.payload;
    if (!payload) return $gettext("Results");
    const text = payload.results.some((hit) => hit.type === "analysis")
        ? $ngettext(
              "Results (%{n} analysis)",
              "Results (%{n} analyses)",
              payload.total,
          )
        : $ngettext(
              "Results (%{n} document)",
              "Results (%{n} documents)",
              payload.total,
          );
    return interpolate(text, { n: payload.total }, true);
});
const drawerVisible = computed({
    get: () => narrow.value && cardOpen.value,
    set: (visible: boolean) => {
        if (!visible) void closeCard();
    },
});

provide(CURTAIN_KEY, curtain);
provide(FOLIO_ZONES_KEY, zones);

useScreenHeading(
    () => heading.value ?? (isUnavailable.value ? backButton.value : null),
);

/**
 * An analysis or identified material opened elsewhere (S1, a card link)
 * brings its page with it, when the focus changes or when the payload first
 * arrives for a focus; a reload never moves the page. The page stays when the
 * focus has a zone on it; otherwise an analysis goes to the page of its first
 * zone.
 */
watch(
    () => store.focus,
    (focus) => {
        pageToFollow = focus !== null;
        followFocus();
    },
);
watch(data, () => {
    if (pageToFollow) followFocus();
});

/**
 * A document opened with active filters and no page named opens on the first
 * page with an analysis they keep; later filter changes do not move the page.
 */
watch(data, (current) => {
    if (!current || landedOn === current.id) return;
    landedOn = current.id;
    if (store.document?.canvas || store.focus !== null || !filtered.value)
        return;
    const first = firstMatchingPage(current.canvases, perPage.value);
    if (first) store.setCanvas(first);
});

/**
 * Keeps the address of the history entry a card was opened over (the one
 * current when the focus goes from none to some, before the URL records it)
 * and the list entry that opened it, if one did.
 */
watch(
    () => store.focus,
    (next, previous) => {
        if (next === null) {
            openedOver = null;
        } else if (previous === null) {
            openedOver = window.location.search;
            openedFrom =
                window.document.activeElement?.closest<HTMLElement>(
                    "[data-focus]",
                )?.dataset.focus ?? null;
        }
    },
    { flush: "sync" },
);

/**
 * On a wide screen, the heading of a newly focused card takes the keyboard
 * focus when the control that opened it is gone (the list of the page, a card
 * of the other kind). In the drawer, the drawer places the focus.
 */
watch(
    () => store.focus,
    (focus) => {
        if (!focus || narrow.value) return;
        const active = window.document.activeElement;
        if (!active || active === window.document.body)
            card.value?.focusHeading();
        window.document
            .getElementById(CARD_HEADING_ID)
            ?.scrollIntoView?.({ block: "nearest" });
    },
    { flush: "post" },
);

function followFocus(): void {
    const focus = store.focus;
    const current = data.value;
    if (!focus || !current) return;
    pageToFollow = false;
    const zoned =
        focus.kind === "sample" ? current.samples : current.characterizations;
    const pages =
        focus.kind === "analysis"
            ? current.annotations
                  .filter((entry) => entry.analysis === focus.id)
                  .map((entry) => entry.canvas)
            : [
                  zoned.find((entry) => entry.id === focus.id)?.zone?.canvas,
              ].filter((canvas): canvas is string => Boolean(canvas));
    const here = currentCanvas.value?.id;
    if (pages.length > 0 && !pages.some((canvas) => canvas === here)) {
        store.setCanvas(pages[0]);
    }
}

function onSelect(focus: Focus): void {
    store.focusOn(focus);
}

/**
 * Clears the focus and gives the keyboard focus back to what opened the card:
 * the list entry, else the marker of the analysis or sample the card showed;
 * the document name takes it when neither is there (an identified material,
 * an analysis without a zone on this page). The page does not scroll to it.
 * When the card was opened over an entry that is this screen without a card,
 * the history steps back to it, so Back does not show the same screen twice.
 */
async function closeCard(): Promise<void> {
    const returnTo =
        focusedAnalysis.value ??
        (openSample.value ? `sample:${openSample.value.id}` : null);
    const entry = openedFrom;
    openedFrom = null;
    const goBack = openedOver !== null && openedOver === addressWithoutCard();
    store.focusOn(null);
    await nextTick();
    if (goBack) window.history.back();
    const item = [
        ...(side.value?.querySelectorAll<HTMLElement>("[data-focus]") ?? []),
    ].find((element) => element.dataset.focus === entry);
    if (item) {
        item.focus({ preventScroll: true });
        item.scrollIntoView?.({ block: "nearest" });
        return;
    }
    if (returnTo) folio.value?.focusTarget(returnTo);
    const active = window.document.activeElement;
    if (!active || active === window.document.body)
        heading.value?.focus({ preventScroll: true });
}

/** Escape closes an open card on a wide screen (the drawer closes itself). */
function onWorkspaceKeydown(event: KeyboardEvent): void {
    if (event.key !== "Escape" || !cardOpen.value || narrow.value) return;
    event.preventDefault();
    void closeCard();
}

function skipToPage(): void {
    folio.value?.focusCurrent();
}

function skipToFilters(): void {
    rail.value?.focusFilters();
}

function skipToCard(): void {
    side.value?.querySelector<HTMLElement>("h3[tabindex='-1']")?.focus();
}

/** The address of this screen with no card open. */
function addressWithoutCard(): string {
    return searchOf(toQuery({ ...snapshotOf(store), focus: null }));
}

function onFacetChange(key: FacetKey, ids: string[]): void {
    store.setFacet(key, ids);
}

function onFolioView(view: FolioView): void {
    store.setFolioView(view);
}

function selectCanvas(canvasId: string): void {
    store.setCanvas(canvasId);
}

function back(): void {
    store.setCorpusScreen(store.documentOrigin);
}

function goHome(): void {
    store.setCorpusScreen("home");
}
</script>

<template>
    <div class="corpus-document">
        <nav
            v-if="data"
            class="skip-links"
            :aria-label="$gettext('Skip links')"
        >
            <button
                type="button"
                class="skip"
                @click="skipToPage"
            >
                <span>{{ $gettext("Go to the page") }}</span>
            </button>
            <button
                type="button"
                class="skip"
                @click="skipToFilters"
            >
                <span>{{ $gettext("Go to the filters") }}</span>
            </button>
            <button
                type="button"
                class="skip"
                @click="skipToCard"
            >
                <span>{{ $gettext("Go to the card") }}</span>
            </button>
        </nav>
        <BusyStatus
            :busy="payload.status.value === 'loading'"
            :first="data === null"
        />
        <button
            ref="back-button"
            type="button"
            class="back"
            @click="back"
        >
            <span>{{ backLabel }}</span>
        </button>
        <UnavailableState
            v-if="isUnavailable"
            :status="payload.status.value === 'error' ? 'error' : 'unavailable'"
            :hide-home="store.documentOrigin !== 'results'"
            @retry="payload.retry"
            @home="goHome"
        />
        <div
            v-else-if="!data"
            class="document-skeleton"
            aria-hidden="true"
        >
            <span class="ms-skeleton title"></span>
            <span class="ms-skeleton meta"></span>
            <div class="columns">
                <span class="ms-skeleton rail-block"></span>
                <span class="ms-skeleton folio-block"></span>
                <span class="ms-skeleton side-block"></span>
            </div>
        </div>
        <template v-else>
            <header class="document-bar">
                <h2
                    ref="heading"
                    class="name"
                    tabindex="-1"
                    :lang="data.name.lang"
                >
                    <span>{{ data.name.value }}</span>
                </h2>
                <p
                    v-if="data.holding"
                    class="holding"
                    :lang="data.holding.lang"
                >
                    <span>{{ data.holding.value }}</span>
                </p>
                <p class="chips">
                    <span class="chip counts">{{ counts }}</span>
                    <span
                        v-if="currentCanvas"
                        class="chip page"
                        >{{ currentCanvas.label }}</span
                    >
                </p>
            </header>
            <DraftBanner :count="data.unpublishedCount" />
            <UnavailableState
                v-if="failed"
                :status="
                    payload.status.value === 'error' ? 'error' : 'unavailable'
                "
                :hide-home="true"
                @retry="payload.retry"
            />
            <div
                class="workspace"
                :aria-busy="
                    payload.status.value === 'loading' ? 'true' : 'false'
                "
                @keydown="onWorkspaceKeydown"
            >
                <RailPanel
                    ref="rail"
                    class="rail"
                    :title="$gettext('Filters of this document')"
                    :show-label="showLabel"
                >
                    <FacetRail
                        :facets="search.data.value?.facets ?? []"
                        :selected="selectedFacets(store.filters)"
                        :count-hint="$gettext('%{n} in this document')"
                        @change="onFacetChange"
                    />
                    <p
                        v-if="store.activeFilterCount > 0"
                        class="rail-foot"
                    >
                        <button
                            type="button"
                            class="clear"
                            @click="store.clearFilters()"
                        >
                            <span>{{ $gettext("Clear") }}</span>
                        </button>
                    </p>
                </RailPanel>
                <section
                    class="stage"
                    :aria-label="$gettext('Page')"
                >
                    <div class="stage-head">
                        <FolioViewSwitch
                            :view="folioView"
                            :available="availableViews"
                            @change="onFolioView"
                        />
                        <p
                            class="page-count"
                            aria-live="polite"
                        >
                            <span>{{ pageCount }}</span>
                        </p>
                    </div>
                    <div class="viewer">
                        <FolioMap
                            ref="folio"
                            :canvas="currentCanvas"
                            :annotations="pageAnnotations"
                            :characterizations="pageCharacterizations"
                            :styles="styles"
                            :focus="store.focus"
                            :slots="slots"
                            :lit="lit"
                            :dimmed-materials="dimmedMaterials"
                            :layers="store.layers"
                            :view="folioView"
                            :samples="pageSamples"
                            :overlays="overlays"
                            :curtain="curtain"
                            :caption="folioCaption"
                            @select="onSelect"
                        />
                        <FolioLegend
                            class="legend"
                            :entries="pageLegend"
                        />
                    </div>
                    <CanvasStrip
                        :canvases="canvases"
                        :current="currentCanvas?.id ?? null"
                        :counts="perPage"
                        :filtered="filtered"
                        @select="selectCanvas"
                    />
                </section>
                <aside
                    ref="side"
                    class="side"
                    :aria-label="$gettext('Details')"
                >
                    <AnalysisCard
                        v-if="!narrow && focusedAnalysis !== null"
                        ref="card"
                        :handle="analysis"
                        :analysis-id="focusedAnalysis"
                        :heading-id="CARD_HEADING_ID"
                        @close="closeCard"
                    />
                    <CharacterizationCard
                        v-else-if="!narrow && openCharacterization"
                        ref="card"
                        :summary="openCharacterization"
                        :scale="certaintyScale"
                        :heading-id="CARD_HEADING_ID"
                        @close="closeCard"
                    />
                    <SampleCard
                        v-else-if="!narrow && openSample"
                        ref="card"
                        :sample="openSample"
                        :analysis-names="analysisNames"
                        :heading-id="CARD_HEADING_ID"
                        @close="closeCard"
                    />
                    <OnThisPage
                        v-else
                        :annotations="pageAnnotations"
                        :unlocated="data.unlocated"
                        :characterizations="listedCharacterizations"
                        :samples="listedSamples"
                        :styles="styles"
                        :view="folioView"
                        :page-label="currentCanvas?.label ?? ''"
                        :document-name="data.name.value"
                        @select="onSelect"
                    />
                    <SelectionPanel />
                </aside>
            </div>
            <Drawer
                v-model:visible="drawerVisible"
                class="explorer-card-drawer"
                :position="phone ? 'bottom' : 'right'"
                :header="$gettext('Details')"
                :pt="{
                    root: {
                        role: 'dialog',
                        'aria-labelledby': CARD_HEADING_ID,
                    },
                }"
            >
                <AnalysisCard
                    v-if="focusedAnalysis !== null"
                    :handle="analysis"
                    :analysis-id="focusedAnalysis"
                    :heading-id="CARD_HEADING_ID"
                    :closable="false"
                    @close="closeCard"
                />
                <CharacterizationCard
                    v-else-if="openCharacterization"
                    :summary="openCharacterization"
                    :scale="certaintyScale"
                    :heading-id="CARD_HEADING_ID"
                    :closable="false"
                    @close="closeCard"
                />
                <SampleCard
                    v-else-if="openSample"
                    :sample="openSample"
                    :analysis-names="analysisNames"
                    :heading-id="CARD_HEADING_ID"
                    :closable="false"
                    @close="closeCard"
                />
            </Drawer>
        </template>
    </div>
</template>

<style scoped>
.corpus-document {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.75rem;
    padding-block: 0.5rem 2rem;
}

.corpus-document .skip-links {
    position: absolute;
    display: flex;
    gap: 0.5rem;
}

.corpus-document .skip {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

.corpus-document .skip:focus {
    position: fixed;
    inset-block-start: var(--explorer-top);
    inset-inline-start: 1rem;
    z-index: 1100;
    inline-size: auto;
    block-size: auto;
    padding: 0.5rem 1rem;
    overflow: visible;
    clip-path: none;
    border: 0.125rem solid var(--blue-text);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-weight: 600;
}

.corpus-document .back {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    justify-self: start;
    min-block-size: var(--explorer-target);
    padding: 0;
    border: none;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    cursor: pointer;
}

.corpus-document .back::before {
    content: "←" / "";
}

.corpus-document .back:hover {
    text-decoration: underline;
}

.corpus-document .document-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.25rem 0.75rem;
}

.corpus-document .document-bar .name {
    font-family: var(--font-display);
    font-size: 1.5rem;
    font-weight: 500;
    line-height: 1.2;
}

.corpus-document .document-bar .holding {
    color: var(--ink-muted);
}

.corpus-document .document-bar .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
}

.corpus-document .document-bar .chip {
    padding: 0.0625rem 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
}

.corpus-document .document-skeleton {
    display: grid;
    gap: 0.75rem;
}

.corpus-document .document-skeleton .title {
    inline-size: min(28rem, 70%);
    block-size: 1.75rem;
}

.corpus-document .document-skeleton .meta {
    inline-size: min(18rem, 50%);
    block-size: 1rem;
}

.corpus-document .document-skeleton .columns {
    display: grid;
    grid-template-columns: var(--explorer-rail) minmax(0, 1fr) var(
            --explorer-side
        );
    gap: 1rem;
}

.corpus-document .document-skeleton .rail-block,
.corpus-document .document-skeleton .side-block {
    block-size: 24rem;
}

.corpus-document .document-skeleton .folio-block {
    block-size: 36rem;
}

.corpus-document .workspace {
    display: grid;
    grid-template-columns: var(--explorer-rail) minmax(0, 1fr) var(
            --explorer-side
        );
    grid-template-areas: "rail stage side";
    gap: 1rem;
    align-items: start;
}

.corpus-document .rail {
    grid-area: rail;
}

.corpus-document .stage,
.corpus-document .side {
    position: sticky;
    inset-block-start: var(--explorer-top);
    max-block-size: calc(100dvh - var(--explorer-top) - 1rem);
    min-inline-size: 0;
    scroll-margin-block-start: var(--explorer-top);
    border: 0.0625rem solid var(--border);
    border-radius: var(--explorer-radius);
    background: var(--surface);
}

.corpus-document .stage {
    grid-area: stage;
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto;
    gap: 0.5rem;
    block-size: calc(100dvh - var(--explorer-top) - 1rem);
    min-block-size: 30rem;
    padding: 0.5rem;
}

.corpus-document .stage-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.25rem 1rem;
}

.corpus-document .stage-head .page-count {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.75rem;
}

.corpus-document .viewer {
    position: relative;
    display: grid;
    min-block-size: 0;
}

.corpus-document .viewer .legend {
    position: absolute;
    inset-block-start: 0.75rem;
    inset-inline-start: 0.75rem;
    z-index: 1000;
    max-inline-size: calc(100% - 5rem);
}

.corpus-document .side {
    grid-area: side;
    display: grid;
    align-content: start;
    gap: 1.25rem;
    padding: 1rem;
    overflow-y: auto;
    overscroll-behavior: contain;
}

.corpus-document .rail-foot {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1rem;
    padding-block-start: 0.75rem;
    border-block-start: 0.0625rem solid var(--border);
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.corpus-document .rail-foot .clear {
    min-block-size: var(--explorer-target);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.corpus-document button:focus-visible,
.corpus-document .name:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

@media (max-width: 80rem) {
    .corpus-document .workspace,
    .corpus-document .document-skeleton .columns {
        grid-template-columns: minmax(0, 1fr) var(--explorer-side);
        grid-template-areas:
            "rail rail"
            "stage side";
    }

    .corpus-document .document-skeleton .rail-block {
        display: none;
    }
}

@media (max-width: 48rem) {
    .corpus-document .workspace,
    .corpus-document .document-skeleton .columns {
        grid-template-columns: minmax(0, 1fr);
        grid-template-areas:
            "rail"
            "stage"
            "side";
    }

    .corpus-document .stage,
    .corpus-document .side {
        position: static;
        max-block-size: none;
    }

    .corpus-document .stage {
        block-size: min(75dvh, 40rem);
        min-block-size: 22rem;
    }

    .corpus-document .document-skeleton .side-block {
        display: none;
    }
}
</style>
