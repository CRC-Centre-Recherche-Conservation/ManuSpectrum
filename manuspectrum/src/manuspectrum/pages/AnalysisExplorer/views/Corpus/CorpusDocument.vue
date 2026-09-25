<script setup lang="ts">
import { computed, nextTick, provide, ref, useTemplateRef, watch } from "vue";
import { useMediaQuery } from "@vueuse/core";
import Drawer from "primevue/drawer";
import { useGettext } from "vue3-gettext";

import DraftBanner from "@/manuspectrum/pages/AnalysisExplorer/components/DraftBanner.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import FacetRail from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetRail.vue";
import AnalysisCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/AnalysisCard.vue";
import CanvasStrip from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/CanvasStrip.vue";
import CharacterizationCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/CharacterizationCard.vue";
import FolioMap from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/FolioMap.vue";
import OnThisPage from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/OnThisPage.vue";
import SelectionPanel from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/SelectionPanel.vue";

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
import { folioOverlays } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import { techniqueStyles } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import {
    CURTAIN_KEY,
    FOLIO_ZONES_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { folioLayerOf } from "@/manuspectrum/pages/AnalysisExplorer/viewers/registry.ts";

import type { FacetKey } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    Focus,
    LayerToggles,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const NARROW_QUERY = "(max-width: 48rem)";
const PHONE_QUERY = "(max-width: 30rem)";

const props = defineProps<{ documentId: string }>();

const store = useExplorerStore();
const { $gettext, $ngettext, interpolate } = useGettext();
const payload = useDocument(
    () => props.documentId,
    () => searchQuery(store.filters, 1),
);
const search = useSearch(() =>
    searchQuery({ ...store.filters, grain: "analyses" }, 1),
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
const folio = useTemplateRef<{ focusTarget: (id: string) => void }>("folio");

const railOpen = ref(false);
const curtain = ref<string | null>(null);

const data = computed(() => payload.data.value);
const isUnavailable = computed(
    () =>
        payload.status.value === "error" ||
        payload.status.value === "unavailable",
);
const certaintyScale = computed(
    () => data.value?.certaintyScale ?? { levels: [] },
);
const canvases = computed(() => data.value?.canvases ?? []);
const currentCanvas = computed(
    () =>
        canvases.value.find((canvas) => canvas.id === store.document?.canvas) ??
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
const styles = computed(() =>
    techniqueStyles(
        [
            ...(data.value?.annotations ?? []).map((entry) => entry.technique),
            ...(data.value?.unlocated ?? []).map((entry) => entry.technique),
        ],
        { value: $gettext("Analysis"), lang: "" },
    ),
);
const legend = computed(() => [...styles.value.values()]);
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
const cardOpen = computed(
    () => focusedAnalysis.value !== null || openCharacterization.value !== null,
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
                        !characterizationMatches(summary, store.filters),
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
/** The layer toggles offered: those that would show or hide something on this page (`folioLayerOf`, as the folio decides). */
const availableLayers = computed(() => ({
    points: pageAnnotations.value.some(
        (entry) => folioLayerOf(entry.dataKind) === "points",
    ),
    zones: pageAnnotations.value.some(
        (entry) => folioLayerOf(entry.dataKind) === "zones",
    ),
    characterizations: pageCharacterizations.value.length > 0,
}));
const railToggleLabel = computed(() =>
    interpolate(
        $gettext("Filters (%{count})"),
        { count: store.activeFilterCount },
        true,
    ),
);
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

/** An analysis or identified material opened elsewhere (S1, a card link) brings its page with it. */
watch(
    () => [store.focus, data.value] as const,
    ([focus, current]) => {
        if (!focus || !current) return;
        const canvas =
            focus.kind === "analysis"
                ? current.annotations.find(
                      (entry) => entry.analysis === focus.id,
                  )?.canvas
                : current.characterizations.find(
                      (summary) => summary.id === focus.id,
                  )?.zone?.canvas;
        if (canvas && canvas !== currentCanvas.value?.id) {
            store.setCanvas(canvas);
        }
    },
);

function onSelect(focus: Focus): void {
    store.focusOn(focus);
}

/**
 * Clears the focus and gives the keyboard focus back to the marker of the
 * analysis the card showed; the document name takes it when no marker does
 * (an identified material, an analysis without a zone on this page).
 */
async function closeCard(): Promise<void> {
    const returnTo = focusedAnalysis.value;
    store.focusOn(null);
    await nextTick();
    if (returnTo) folio.value?.focusTarget(returnTo);
    const active = window.document.activeElement;
    if (!active || active === window.document.body) heading.value?.focus();
}

function onFacetChange(key: FacetKey, ids: string[]): void {
    store.setFacet(key, ids);
}

function toggleLayer(key: keyof LayerToggles, event: Event): void {
    store.setLayer(key, (event.target as HTMLInputElement).checked);
}

function toggleRail(): void {
    railOpen.value = !railOpen.value;
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
        <button
            ref="back-button"
            type="button"
            class="back"
            @click="back"
        >
            <span v-if="store.documentOrigin === 'results'">{{
                $gettext("Back to the results")
            }}</span>
            <span v-else>{{ $gettext("Back to the explorer home") }}</span>
        </button>
        <UnavailableState
            v-if="isUnavailable"
            :status="payload.status.value === 'error' ? 'error' : 'unavailable'"
            :hide-home="store.documentOrigin !== 'results'"
            @retry="payload.retry"
            @home="goHome"
        />
        <template v-else-if="data">
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
                <p class="counts">
                    <span>{{ counts }}</span>
                </p>
                <DraftBanner :count="data.unpublishedCount" />
            </header>
            <CanvasStrip
                :canvases="canvases"
                :current="currentCanvas?.id ?? null"
                @select="selectCanvas"
            />
            <div
                class="workspace"
                :class="{ 'rail-open': railOpen }"
                :aria-busy="
                    payload.status.value === 'loading' ? 'true' : 'false'
                "
            >
                <aside
                    class="rail"
                    :aria-label="$gettext('Filters')"
                >
                    <button
                        type="button"
                        class="rail-toggle"
                        aria-controls="explorer-document-rail"
                        :aria-expanded="railOpen ? 'true' : 'false'"
                        @click="toggleRail"
                    >
                        <span>{{ railToggleLabel }}</span>
                    </button>
                    <div
                        id="explorer-document-rail"
                        class="rail-body"
                    >
                        <FacetRail
                            :facets="search.data.value?.facets ?? []"
                            @change="onFacetChange"
                        />
                        <p class="rail-foot">
                            <span>{{ pageCount }}</span>
                            <button
                                v-if="store.activeFilterCount > 0"
                                type="button"
                                class="clear"
                                @click="store.clearFilters()"
                            >
                                <span>{{ $gettext("Clear") }}</span>
                            </button>
                        </p>
                    </div>
                </aside>
                <section
                    class="stage"
                    :aria-label="$gettext('Page')"
                >
                    <fieldset class="layers">
                        <legend>
                            <span>{{ $gettext("Layers") }}</span>
                        </legend>
                        <label v-if="availableLayers.points">
                            <input
                                type="checkbox"
                                :checked="store.layers.points"
                                @change="toggleLayer('points', $event)"
                            />
                            <span>{{ $gettext("Point analyses") }}</span>
                        </label>
                        <label v-if="availableLayers.zones">
                            <input
                                type="checkbox"
                                :checked="store.layers.zones"
                                @change="toggleLayer('zones', $event)"
                            />
                            <span>{{ $gettext("Imaging zones") }}</span>
                        </label>
                        <label v-if="availableLayers.characterizations">
                            <input
                                type="checkbox"
                                :checked="store.layers.characterizations"
                                @change="
                                    toggleLayer('characterizations', $event)
                                "
                            />
                            <span>{{ $gettext("Identified materials") }}</span>
                        </label>
                    </fieldset>
                    <ul
                        v-if="legend.length > 0"
                        class="legend"
                        :aria-label="$gettext('Techniques')"
                    >
                        <li
                            v-for="style in legend"
                            :key="style.key"
                        >
                            <span
                                class="code"
                                aria-hidden="true"
                                :class="
                                    style.colour
                                        ? `code--tech-${style.colour}`
                                        : 'code--ink'
                                "
                            >
                                {{ style.code }}
                            </span>
                            <span :lang="style.label.lang || undefined">{{
                                style.label.value
                            }}</span>
                        </li>
                    </ul>
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
                        :overlays="overlays"
                        :curtain="curtain"
                        @select="onSelect"
                    />
                </section>
                <aside
                    class="side"
                    :aria-label="$gettext('Details')"
                >
                    <AnalysisCard
                        v-if="!narrow && focusedAnalysis !== null"
                        :handle="analysis"
                        @close="closeCard"
                    />
                    <CharacterizationCard
                        v-else-if="!narrow && openCharacterization"
                        :summary="openCharacterization"
                        :scale="certaintyScale"
                        @close="closeCard"
                    />
                    <OnThisPage
                        v-else
                        :annotations="pageAnnotations"
                        :unlocated="data.unlocated"
                        :characterizations="listedCharacterizations"
                        :styles="styles"
                        @select="onSelect"
                    />
                    <SelectionPanel />
                </aside>
            </div>
            <Drawer
                v-model:visible="drawerVisible"
                class="card-drawer"
                :position="phone ? 'bottom' : 'right'"
                :header="$gettext('Details')"
            >
                <AnalysisCard
                    v-if="focusedAnalysis !== null"
                    :handle="analysis"
                    @close="closeCard"
                />
                <CharacterizationCard
                    v-else-if="openCharacterization"
                    :summary="openCharacterization"
                    :scale="certaintyScale"
                    @close="closeCard"
                />
            </Drawer>
        </template>
    </div>
</template>

<style scoped>
.corpus-document {
    display: grid;
    gap: 1rem;
    padding-block: 1rem 2rem;
}

.corpus-document .back {
    justify-self: start;
    min-block-size: 2.75rem;
    border: none;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    text-decoration: underline;
    cursor: pointer;
}

.corpus-document .document-bar {
    display: grid;
    gap: 0.25rem;
}

.corpus-document .document-bar .name {
    font-family: var(--font-display);
    font-size: 2rem;
    font-weight: 500;
}

.corpus-document .document-bar .holding,
.corpus-document .document-bar .counts {
    color: var(--ink-muted);
}

.corpus-document .workspace {
    display: grid;
    grid-template-columns: 16rem minmax(0, 1fr) 24rem;
    gap: 1.5rem;
    align-items: start;
}

.corpus-document .rail,
.corpus-document .rail-body,
.corpus-document .stage,
.corpus-document .side {
    display: grid;
    align-content: start;
    gap: 1rem;
    min-inline-size: 0;
}

.corpus-document .rail-toggle {
    display: none;
}

.corpus-document .rail-toggle,
.corpus-document .rail-foot .clear {
    min-block-size: 2.75rem;
    padding-inline: 1rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.corpus-document .rail-foot {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1rem;
    color: var(--ink-muted);
}

.corpus-document .layers {
    display: flex;
    flex-wrap: wrap;
    gap: 0 1.5rem;
    border: none;
}

.corpus-document .layers legend {
    font-weight: 600;
}

.corpus-document .layers label {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: 2.75rem;
    cursor: pointer;
}

.corpus-document .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1.25rem;
    padding: 0;
    list-style: none;
}

.corpus-document .legend li {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
}

.corpus-document .legend .code {
    display: inline-grid;
    place-items: center;
    inline-size: 1.5rem;
    block-size: 1.5rem;
    border: 0.125rem solid var(--surface);
    border-radius: 50%;
    background: var(--ink);
    color: var(--stage);
    font: 600 0.6875rem var(--font-body);
}

.corpus-document .legend .code--tech-1 {
    background: var(--tech-1);
}

.corpus-document .legend .code--tech-2 {
    background: var(--tech-2);
}

.corpus-document .legend .code--tech-3 {
    background: var(--tech-3);
}

.corpus-document .legend .code--tech-4 {
    background: var(--tech-4);
}

.corpus-document .legend .code--tech-5 {
    background: var(--tech-5);
}

.corpus-document .legend .code--tech-6 {
    background: var(--tech-6);
}

.corpus-document .legend .code--ink {
    background: var(--surface);
    color: var(--ink);
}

.corpus-document button:focus-visible,
.corpus-document input:focus-visible,
.corpus-document .name:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

@media (max-width: 80rem) {
    .corpus-document .workspace {
        grid-template-columns: minmax(0, 1fr) 22rem;
    }

    .corpus-document .rail {
        grid-column: 1 / -1;
    }

    .corpus-document .rail-toggle {
        display: inline-flex;
        align-items: center;
        justify-self: start;
    }

    .corpus-document .workspace:not(.rail-open) .rail-body {
        display: none;
    }
}

@media (max-width: 48rem) {
    .corpus-document .workspace {
        grid-template-columns: minmax(0, 1fr);
    }
}
</style>
