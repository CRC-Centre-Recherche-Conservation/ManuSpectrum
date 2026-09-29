<script setup lang="ts">
import { computed, provide, ref } from "vue";
import { useGettext } from "vue3-gettext";

import LoadingSpinner from "@/manuspectrum/pages/AnalysisExplorer/components/LoadingSpinner.vue";
import ImagingPreview from "@/manuspectrum/pages/AnalysisExplorer/viewers/ImagingPreview.vue";
import ChemicalImagingStage from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ChemicalImagingStage.vue";
import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import { useDocument } from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocument.ts";
import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { documentView } from "@/manuspectrum/pages/AnalysisExplorer/folio/document-view.ts";
import {
    markedZones,
    shapeBounds,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import {
    CURTAIN_KEY,
    FOLIO_ZONES_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    analysisNode,
    slotNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type {
    AnalysisHit,
    FileEntry,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LatLng } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";

type Mode = "reading" | "folio" | "no-zone" | "no-image" | "error";

/**
 * One map of the « Chemical imaging » window, under its slot and name: the
 * document screen's imaging preview (`ImagingPreview`) showing the layer
 * held (`held`; null when the map lacks the layer `wanted`: the map then
 * says so and lists the layers it has; undefined leaves the map its own
 * layer scroll). Laid on the page, the layer goes over the analysis's zone
 * on its page (`ChemicalImagingStage`), under a curtain of this map's own.
 * The page comes from the document payload (`useDocument`, the tab memo);
 * without a zone with an extent, a page image or a readable document, the
 * map is shown alone. The card stands for its analysis (`an:`): the
 * analysis name is its toggle, carrying the focus marks, and the card is
 * tinted by how the analysis stands to the focus (an unlinked map fades)
 * and to the node a mouse previews.
 */
const props = defineProps<{
    slotNumber: number;
    analysis: AnalysisHit;
    file: FileEntry;
    held: number | null | undefined;
    /** The label of the layer held on every map; null when there is none. */
    wanted: string | null;
}>();

const { $gettext, interpolate } = useGettext();
const marks = useLinkedMarks();

const curtain = ref<string | null>(null);

const record = computed(() => analysisNode(props.analysis.id));
const documentId = computed(() =>
    props.analysis.canvas ? props.analysis.document.id : null,
);
const documentRequest = useDocument(() => documentId.value);
const payload = computed(() =>
    documentId.value !== null &&
    documentRequest.loaded.value === documentId.value
        ? documentRequest.data.value
        : null,
);
const service = computed(
    () =>
        payload.value?.canvases.find(
            (entry) => entry.id === props.analysis.canvas,
        )?.image.service ?? null,
);
const bounds = computed<[LatLng, LatLng] | null>(() => {
    if (!payload.value) return null;
    const zone = markedZones(
        documentView(payload.value, null).annotations.filter(
            (annotation) =>
                annotation.analysis === props.analysis.id &&
                annotation.canvas === props.analysis.canvas,
        ),
    )[0];
    return zone ? shapeBounds(zone.shape) : null;
});
const mode = computed<Mode>(() => {
    if (documentId.value === null) return "no-zone";
    const status = documentRequest.status.value;
    if (status === "error" || status === "unavailable") return "error";
    if (!payload.value) return "reading";
    if (!bounds.value) return "no-zone";
    return service.value ? "folio" : "no-image";
});
/** The analysis can be laid on its page while the page is being read or is known. */
const zones = computed<ReadonlySet<string>>(
    () =>
        new Set(
            mode.value === "folio" || mode.value === "reading"
                ? [props.analysis.id]
                : [],
        ),
);
const notMappedText = computed(() =>
    props.wanted === null
        ? $gettext("No layer for this map")
        : interpolate(
              $gettext("No %{layer} layer for this map"),
              { layer: props.wanted },
              true,
          ),
);
const heldText = computed(() =>
    props.file.layers.length === 0
        ? ""
        : interpolate(
              $gettext("Its layers: %{layers}"),
              {
                  layers: props.file.layers
                      .map((layer) => layer.label)
                      .join(", "),
              },
              true,
          ),
);
const aloneNote = computed(() => {
    switch (mode.value) {
        case "no-image":
            return $gettext("No image for this page: the map is shown alone.");
        case "error":
            return $gettext(
                "The document could not be read: the map is shown alone.",
            );
        default:
            return "";
    }
});

provide(CURTAIN_KEY, curtain);
provide(FOLIO_ZONES_KEY, zones);
</script>

<template>
    <figure
        class="chemical-imaging-map"
        :data-rel="marks.rel(record)"
        :data-preview="marks.previewRel(record)"
        :style="marks.rowStyle(record)"
        @pointerenter="marks.enter(record, $event)"
        @pointerleave="marks.leave($event)"
    >
        <figcaption>
            <span
                class="slot"
                :data-rel="marks.rel(slotNode(props.slotNumber))"
                >{{ slotLabel(props.slotNumber) }}</span
            >
            <button
                type="button"
                class="record ms-focus"
                v-bind="marks.focus(record)"
                :title="props.analysis.name.value"
                :lang="props.analysis.name.lang"
                :aria-pressed="marks.pressed(record)"
                @click="marks.toggle(record)"
            >
                <FocusPip :node="record" />
                <span>{{ props.analysis.name.value }}</span>
            </button>
            <span
                class="file"
                :title="props.file.name"
                >{{ props.file.name }}</span
            >
        </figcaption>
        <ImagingPreview
            :file="props.file"
            :analysis="props.analysis"
            :held="props.held"
            :contrast-note="false"
        >
            <template #missing>
                <div class="not-mapped">
                    <svg
                        :viewBox="ICON_VIEW_BOX"
                        aria-hidden="true"
                        focusable="false"
                    >
                        <path
                            v-for="(path, index) in ICONS.image"
                            :key="index"
                            :d="path"
                        />
                    </svg>
                    <p class="message">
                        <span>{{ notMappedText }}</span>
                    </p>
                    <p
                        v-if="heldText"
                        class="held"
                    >
                        <span>{{ heldText }}</span>
                    </p>
                </div>
            </template>
            <template
                v-if="mode === 'folio' || mode === 'reading'"
                #stage="stage"
            >
                <ChemicalImagingStage
                    v-if="mode === 'folio' && service && bounds"
                    :service="service"
                    :bounds="bounds"
                    :layer="stage.layer"
                    :opacity="stage.opacity"
                    :under-curtain="stage.underCurtain"
                    :attempt="stage.attempt"
                    @failed="stage.failed"
                />
                <p
                    v-else
                    class="loading"
                    role="status"
                >
                    <LoadingSpinner />
                    <span>{{ $gettext("Reading the document…") }}</span>
                </p>
            </template>
        </ImagingPreview>
        <p
            v-if="aloneNote"
            class="note"
        >
            <span>{{ aloneNote }}</span>
            <button
                v-if="mode === 'error'"
                type="button"
                class="retry"
                @click="documentRequest.retry"
            >
                <span>{{ $gettext("Retry") }}</span>
            </button>
        </p>
    </figure>
</template>

<style scoped>
.chemical-imaging-map {
    display: grid;
    align-content: start;
    gap: 0.5rem;
    margin: 0;
    padding: 0.5rem;
    border: 0.0625rem solid var(--border);
    border-radius: 0.375rem;
    background: var(--surface);
}

.chemical-imaging-map:is(
        [data-rel="self"],
        [data-rel="direct"],
        [data-rel="evidence"]
    ) {
    border-color: color-mix(
        in srgb,
        var(--h1, var(--focus-1)) 22%,
        var(--border)
    );
    background: color-mix(
        in srgb,
        var(--h1, var(--focus-1)) 6%,
        var(--surface)
    );
}

.chemical-imaging-map[data-rel="none"] :deep(.layer-image),
.chemical-imaging-map[data-rel="none"] :deep(.chemical-imaging-stage) {
    opacity: var(--linked-fade, 0.35);
}

.chemical-imaging-map[data-rel="none"] figcaption {
    color: var(--ink-muted);
}

.chemical-imaging-map[data-preview] {
    background: color-mix(
        in srgb,
        var(--hp, var(--focus-1)) 5%,
        var(--surface)
    );
}

@media (prefers-reduced-motion: no-preference) {
    .chemical-imaging-map :deep(.layer-image),
    .chemical-imaging-map :deep(.chemical-imaging-stage) {
        transition: opacity 0.15s ease-out;
    }
}

.chemical-imaging-map figcaption {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: 0 0.5rem;
    font-size: 0.8125rem;
}

.chemical-imaging-map figcaption .record > span:last-child,
.chemical-imaging-map figcaption .file {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.chemical-imaging-map figcaption .record {
    display: flex;
    justify-self: start;
    max-inline-size: 100%;
    min-inline-size: 0;
}

.chemical-imaging-map .slot {
    font-family: var(--font-mono);
    font-weight: 600;
}

.chemical-imaging-map .record {
    --r: 0.375rem;
    --link-pip: 0.8125rem;
    min-block-size: 1.5rem;
    padding: 0 0.25rem;
    border: 0.0625rem solid transparent;
    border-radius: 0.375rem;
    background: none;
    color: inherit;
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.chemical-imaging-map .record:hover {
    border-color: var(--border-hover);
}

.chemical-imaging-map .file {
    grid-column: 1 / -1;
    color: var(--ink-muted);
}

.chemical-imaging-map :deep(.layer-image) {
    inline-size: 100%;
    block-size: auto;
    max-block-size: 70vh;
    border-radius: var(--explorer-radius, 0.625rem);
    object-fit: contain;
}

.chemical-imaging-map .not-mapped {
    display: grid;
    justify-items: center;
    align-content: center;
    gap: 0.375rem;
    min-block-size: 10rem;
    padding: 0.75rem;
    border-radius: var(--explorer-radius, 0.625rem);
    background: var(--bg-alt);
    color: var(--ink-muted);
    font-size: 0.8125rem;
    text-align: center;
}

.chemical-imaging-map .not-mapped svg {
    inline-size: 1.5rem;
    block-size: 1.5rem;
    fill: currentColor;
}

.chemical-imaging-map .not-mapped .message {
    margin: 0;
    color: var(--ink);
    font-weight: 600;
}

.chemical-imaging-map .not-mapped .held {
    margin: 0;
}

.chemical-imaging-map .loading {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: 14rem;
    color: var(--ink-muted);
}

.chemical-imaging-map .note {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin: 0;
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.chemical-imaging-map .note .retry {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: none;
    border-radius: 0.375rem;
    background: var(--bg-alt);
    color: var(--ink);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
}

.chemical-imaging-map button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
