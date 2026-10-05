<script setup lang="ts">
import {
    computed,
    inject,
    onBeforeUnmount,
    onMounted,
    ref,
    useId,
    useTemplateRef,
    watch,
} from "vue";
import L from "leaflet";
import { useGettext } from "vue3-gettext";
import { stackSmallestOnTop } from "utils/leaflet-stack";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
import LoadingSpinner from "@/manuspectrum/pages/AnalysisExplorer/components/LoadingSpinner.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import TechniqueCode from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/TechniqueCode.vue";
import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";

import { useDocument } from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocument.ts";
import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import {
    componentOutlines,
    shapeBounds,
    shapeCentre,
    shapeCorner,
    shapeFeature,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import {
    fitPage,
    layPage,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import {
    FOLIO_REQUEST_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    analysisNode,
    componentNode,
    materialNode,
    slotNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { folioMarks } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";
import { itemClasses } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";

import type { Feature } from "geojson";
import type { SynthesisCanvas } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedMark } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import type { PreviewEvent } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { ComponentOutline } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import type { PageLayer } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";
import type { FolioMark } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";

/** The Leaflet layers drawn for one mark, restyled in place. */
interface DrawnMark {
    marker: L.Marker | null;
    halo: L.GeoJSON;
    frame: L.GeoJSON;
}

/** The Leaflet layers drawn for one Component outline, restyled in place. */
interface DrawnOutline {
    outline: L.GeoJSON;
    label: L.Marker | null;
}

const MAX_ZOOM = 8;
const INITIAL_ZOOM = 2;
const MARKER_SIZE = 28;
/** Advance of one character of the marker's 0.625rem monospace label, rounded up, in px. */
const MARKER_CHAR_WIDTH = 6.25;
/** The marker's inline padding and border, in px. */
const MARKER_INSET = 12;
const FRAME_WEIGHT = 2;
const LINKED_FRAME_WEIGHT = 3;
const SELF_FRAME_WEIGHT = 4;
/** 2px wider than the heaviest frame (`SELF_FRAME_WEIGHT`), so its halo margin never runs thinner than the others. */
const HALO_WEIGHT = 6;
const HALO_OPACITY = 0.9;
/** The opacity of what the selection does not link (`--linked-fade`). */
const FADED_OPACITY = 0.35;
const FRAME_DASH = "4 4";
const OUTLINE_WEIGHT = 1.5;
/** The fill of a Component outline the focus links (`self`, `direct`). */
const OUTLINE_TINT = 0.08;
/** Keeps the Components' labels under the analyses' markers. */
const OUTLINE_LABEL_Z = -1000;
/** The stroke of a zone or outline the preview links, by level. */
const PREVIEW_WEIGHT: Record<RelationLevel, number> = {
    self: 2.5,
    direct: 1.5,
    evidence: 1,
};
/** The fill of a zone or outline the preview links, by level. */
const PREVIEW_FILL: Record<RelationLevel, number> = {
    self: 0.16,
    direct: 0.07,
    evidence: 0.04,
};
const RELATED_PADDING = 0.25;
/** The other folios « Show » buttons are offered for. */
const SHOWN_ELSEWHERE = 3;
const NO_IMAGE_PADDING = 0.5;
/**
 * The folio image tool: one of the canvases the Selection's items are
 * placed on (picked among `canvases`, the first at first) with the
 * Selection's analyses and identified materials placed on it, each marked
 * with its A-labels in the colour and marker of its first slot (`itemClasses`) and its
 * zones framed in that colour over a halo; the same
 * marks are listed under the image. The page comes from the document
 * payload (`useDocument`, the tab memo the document screen shares). The
 * markers are labels, not controls: the list is what assistive
 * technologies read.
 *
 * Each mark stands for its record (`an:`, `ch:`): its name in the list is
 * the record's toggle, carrying the focus marks, and the mark is shown by
 * how the record stands to the focus (an unlinked zone fades, an unlinked
 * marker's fill fades under a label turned to ink, a linked frame is drawn
 * solid and heavier in the hue of its first slot, its marker ringed in
 * that hue) and to the node a mouse previews, in the hue of the slot the
 * pin would take: every zone the preview links is stroked solid and
 * tinted (1.5 at 7 %, 1 at 4 % for evidence), its marker ringed; the
 * previewed record's own zones are stroked at 2.5 with a glow, and a light
 * runs once around each of them on its halo (`pathLength` 100; none under
 * reduced motion). A focus change restyles the layers drawn (`setStyle`
 * for the weights and fills; the hue as the `--frame-hue` property and
 * `data-preview` of each path, which the stylesheet strokes with, and
 * `--h1`, `--hp`, `data-*` on the markers) and never draws them again. A marker carries
 * the `data-node` and `data-slots` of its record, which its window counts. The whole page is fitted to the
 * stage again when the window changes size, until the reader moves the view
 * (a pointer, the wheel or the keyboard on the map, « Fit to related »);
 * « Whole page » and another folio fit it again. « Fit to related » frames the
 * linked marks of the page; when linked items of the Selection are placed
 * on other folios they are named, each with a button showing it.
 *
 * The folio is picked in a menu between « Previous folio » and « Next
 * folio » (each unavailable at its end of `canvases`), or asked by Compare
 * (`FOLIO_REQUEST_KEY`: a folio of the coverage matrix clicked), which the
 * tool follows when the folio is one of its `canvases`.
 *
 * Under the zones, each Component of the document placed on the folio
 * (`DocumentPayload.components`) is outlined thinly with its name; the
 * outline and its line in the list below toggle the Component (`comp:`)
 * and preview it under a mouse. A linked outline (`self`, `direct`) is
 * stroked and tinted in its first slot's hue, an unlinked one fades, and
 * a previewed one is stroked and tinted like the zones; a focus change
 * restyles it like the zones.
 */
const props = defineProps<{
    canvases: readonly SynthesisCanvas[];
    /** Slots of the Selection's analyses and identified materials, by id (`selectionSlots`). */
    slots: ReadonlyMap<string, readonly number[]>;
}>();

const resizeTick = inject(WINDOW_RESIZE_KEY, ref(0), false);
const folioRequests = inject(FOLIO_REQUEST_KEY, null);

const gettext = useGettext();
const { $gettext, interpolate } = gettext;
const pickerId = useId();
const linkedMarks = useLinkedMarks();
const host = useTemplateRef<HTMLDivElement>("host");

const chosen = ref<string | null>(props.canvases[0]?.canvas ?? null);
const pageFailed = ref(false);

// Leaflet objects live outside Vue reactivity.
let map: L.Map | null = null;
let page: PageLayer | null = null;
let drawn: L.LayerGroup | null = null;
let fitted: string | null = null;
/** Whether the view is still the whole page: the reader has not moved it since it was fitted. */
let pageView = true;
/** The kind of the last pointer over the map; Leaflet hands the outlines only mouse events, touch taps' included. */
let lastPointerType = "mouse";
const drawnMarks = new Map<NodeId, DrawnMark>();
const drawnOutlines = new Map<NodeId, DrawnOutline>();

const row = computed(
    () =>
        props.canvases.find((entry) => entry.canvas === chosen.value) ??
        props.canvases[0] ??
        null,
);
/** The position of the folio shown in `canvases`. */
const position = computed(() =>
    row.value ? props.canvases.indexOf(row.value) : -1,
);
const documentRequest = useDocument(() => row.value?.document ?? null);
const payload = computed(() =>
    documentRequest.loaded.value === row.value?.document
        ? documentRequest.data.value
        : null,
);
const canvas = computed(
    () =>
        payload.value?.canvases.find(
            (entry) => entry.id === row.value?.canvas,
        ) ?? null,
);
const folioMarksShown = computed<FolioMark[]>(() =>
    payload.value && row.value
        ? folioMarks(payload.value, row.value.canvas, props.slots)
        : [],
);
/** The outlines of the components the Selection reaches (all of them outside a Compare view). */
const outlinesShown = computed<ComponentOutline[]>(() => {
    if (!payload.value || !row.value) return [];
    const nodes = linkedMarks.linked?.graph.value.nodes;
    return componentOutlines(payload.value, row.value.canvas).filter(
        (outline) => !nodes || nodes.has(componentNode(outline.id)),
    );
});
const hasImage = computed(() => Boolean(canvas.value?.image.service));
/** The marks of the page the selection links. */
const relatedHere = computed(() =>
    folioMarksShown.value.filter((mark) =>
        isLinked(linkedMarks.rel(nodeOf(mark))),
    ),
);
/** The other folios holding a Selection item the selection links. */
const elsewhere = computed(() =>
    props.canvases.filter(
        (entry) =>
            entry.canvas !== row.value?.canvas &&
            isLinked(
                linkedMarks.rel(
                    [
                        ...entry.analyses.map(analysisNode),
                        ...entry.materials.map(materialNode),
                    ].filter(inSelection),
                ),
            ),
    ),
);
const elsewhereText = computed(() => {
    if (elsewhere.value.length === 0) return "";
    const selected = linkedMarks.linked?.selection.value ?? [];
    const name =
        (selected.length === 1
            ? linkedMarks.linked?.labelOf(selected[0])?.value
            : null) ?? $gettext("The selection");
    const folios = new Intl.ListFormat(gettext.current, {
        type: "conjunction",
    }).format(elsewhere.value.map((entry) => entry.label));
    return interpolate(
        relatedHere.value.length > 0
            ? $gettext("%{name} also appears on %{folios}.")
            : $gettext("%{name} appears on %{folios}."),
        { name, folios },
        true,
    );
});

watch(
    () => props.canvases.map((entry) => entry.canvas),
    (canvases) => {
        if (chosen.value === null || !canvases.includes(chosen.value)) {
            chosen.value = canvases[0] ?? null;
        }
    },
);
watch(
    () => folioRequests?.asked.value,
    (asked) => {
        if (
            asked &&
            props.canvases.some((entry) => entry.canvas === asked.canvas)
        ) {
            chosen.value = asked.canvas;
        }
    },
);
watch(() => canvas.value?.id, drawPage);
watch([folioMarksShown, outlinesShown], drawMarks);
watch(
    () => [
        linkedMarks.linked?.relations.value,
        linkedMarks.linked?.previewLevels.value,
        linkedMarks.linked?.previewSlot.value,
    ],
    restyle,
);
watch(resizeTick, () => {
    map?.invalidateSize({ animate: false });
    if (map && pageView) fitPage(map, page);
});
watch(
    () => payload.value !== null,
    (shown) => {
        if (shown) map?.invalidateSize({ animate: false });
    },
    { flush: "post" },
);

onMounted(() => {
    const surface = host.value?.querySelector<HTMLElement>(".surface");
    if (!surface) return;
    map = L.map(surface, {
        crs: L.CRS.Simple,
        attributionControl: false,
        minZoom: 0,
        maxZoom: MAX_ZOOM,
        zoomSnap: 0.25,
    });
    map.setView([0, 0], INITIAL_ZOOM);
    surface.addEventListener("pointerover", notePointer, true);
    surface.addEventListener("pointerdown", notePointer, true);
    stackSmallestOnTop(map);
    drawPage();
    drawMarks();
});

onBeforeUnmount(() => {
    page?.remove();
    page = null;
    map?.remove();
    map = null;
});

function nodeOf(mark: FolioMark): NodeId {
    return mark.kind === "analysis"
        ? analysisNode(mark.id)
        : materialNode(mark.id);
}

function isLinked(mark: LinkedMark | undefined): boolean {
    return mark !== undefined && mark !== "none";
}

function inSelection(id: NodeId): boolean {
    return props.slots.has(id.slice(id.indexOf(":") + 1));
}

function slotClass(mark: FolioMark): string {
    return itemClasses(mark.slots[0]);
}

function slotsText(mark: FolioMark): string {
    return mark.slots.map(slotLabel).join(" ");
}

function onPick(event: Event): void {
    chosen.value = (event.target as HTMLSelectElement).value;
}

/** Shows the folio `step` places away in `canvases`, if there is one. */
function step(by: number): void {
    const next = props.canvases[position.value + by];
    if (next) chosen.value = next.canvas;
}

function drawPage(): void {
    if (!map) return;
    page?.remove();
    page = null;
    pageFailed.value = false;
    pageView = true;
    const service = canvas.value?.image.service;
    if (!service) return;
    page = layPage(map, service, () => {
        pageFailed.value = true;
    });
}

/** A marker as wide as its label (at least a disc), centred on its point. */
function markerIcon(mark: FolioMark): L.DivIcon {
    const text = slotsText(mark);
    const element = document.createElement("span");
    element.className = `folio-tool-marker ${slotClass(mark)}`;
    element.textContent = text;
    element.setAttribute("aria-hidden", "true");
    const width = Math.max(
        MARKER_SIZE,
        Math.ceil(text.length * MARKER_CHAR_WIDTH + MARKER_INSET),
    );
    return L.divIcon({
        html: element,
        className: "folio-tool-marker-host",
        iconSize: [width, MARKER_SIZE],
        iconAnchor: [width / 2, MARKER_SIZE / 2],
    });
}

/** The zone `frames` drawn with `className` at `weight`. */
function frameLayer(
    frames: Feature[],
    className: string,
    weight: number,
): L.GeoJSON {
    return L.geoJSON(frames, {
        style: () => ({
            className,
            weight,
            opacity: className === "folio-tool-halo" ? HALO_OPACITY : 1,
            dashArray: className === "folio-tool-halo" ? "" : FRAME_DASH,
            fill: false,
            interactive: false,
        }),
    });
}

/** The name of a Component, set inside the north-west corner of its outline. */
function outlineLabel(outline: ComponentOutline): L.DivIcon {
    const element = document.createElement("span");
    element.className = "folio-tool-outline-label";
    element.textContent = outline.name.value;
    element.lang = outline.name.lang;
    element.setAttribute("aria-hidden", "true");
    return L.divIcon({
        html: element,
        className: "folio-tool-outline-label-host",
        iconSize: undefined,
        iconAnchor: [-2, -2],
    });
}

function notePointer(event: PointerEvent): void {
    lastPointerType = event.pointerType;
}

/** The kind of pointer behind a Leaflet mouse event: a touch tap's compatibility mouse events are `touch`. */
function pointerTypeOf(original: MouseEvent | undefined): string {
    if (!original) return lastPointerType;
    if ("pointerType" in original)
        return (original as PointerEvent).pointerType;
    const capabilities = (
        original as MouseEvent & {
            sourceCapabilities?: { firesTouchEvents?: boolean } | null;
        }
    ).sourceCapabilities;
    return capabilities?.firesTouchEvents ? "touch" : lastPointerType;
}

function previewEvent(event: L.LeafletEvent): PreviewEvent {
    const original = (event as L.LeafletMouseEvent).originalEvent;
    const path = (event.propagatedFrom as L.Path | undefined)?.getElement?.();
    return {
        pointerType: pointerTypeOf(original),
        currentTarget: path ?? null,
    };
}

/** Each Component outline, its name at its first zone's corner; the outline toggles and previews the Component. */
function drawOutlines(group: L.LayerGroup): void {
    for (const outline of outlinesShown.value) {
        const node = componentNode(outline.id);
        const features = outline.shapes.flatMap((shape) => {
            const feature = shapeFeature(shape, { id: outline.id });
            return feature ? [feature] : [];
        });
        const layer = L.geoJSON(features, {
            style: () => ({
                className: "folio-tool-outline",
                weight: OUTLINE_WEIGHT,
                opacity: 1,
                fill: true,
                fillOpacity: 0,
            }),
        });
        layer.on("click", () => linkedMarks.toggle(node));
        layer.on("mouseover", (event) =>
            linkedMarks.enter(node, previewEvent(event)),
        );
        layer.on("mouseout", (event) => linkedMarks.leave(previewEvent(event)));
        group.addLayer(layer);
        const corner = shapeCorner(outline.shapes[0]);
        const label = corner
            ? L.marker(corner, {
                  icon: outlineLabel(outline),
                  interactive: false,
                  keyboard: false,
                  zIndexOffset: OUTLINE_LABEL_Z,
              })
            : null;
        if (label) group.addLayer(label);
        drawnOutlines.set(node, { outline: layer, label });
    }
}

/** The Component outlines under a marker on each item's first zone with an extent, else its first point; every extent framed in the slot colour, every halo drawn under every frame. */
function drawMarks(): void {
    if (!map) return;
    drawn?.remove();
    drawnMarks.clear();
    drawnOutlines.clear();
    drawn = L.layerGroup().addTo(map);
    drawOutlines(drawn);
    const markers: L.Marker[] = [];
    const framed: [FolioMark, Feature[], L.Marker | null][] = [];
    for (const mark of folioMarksShown.value) {
        const anchor =
            mark.shapes.find((shape) => shapeBounds(shape) !== null) ??
            mark.shapes[0];
        const centre = shapeCentre(anchor);
        let marker: L.Marker | null = null;
        if (centre) {
            marker = L.marker(centre, {
                icon: markerIcon(mark),
                interactive: false,
                keyboard: false,
            });
            markers.push(marker);
            drawn.addLayer(marker);
        }
        const frames = mark.shapes.flatMap((shape) => {
            const feature =
                shape.type === "point"
                    ? null
                    : shapeFeature(shape, { id: mark.id });
            return feature ? [feature] : [];
        });
        framed.push([mark, frames, marker]);
    }
    const halos = framed.map(([, frames]) =>
        frameLayer(frames, "folio-tool-halo", HALO_WEIGHT),
    );
    for (const halo of halos) drawn.addLayer(halo);
    framed.forEach(([mark, frames, marker], index) => {
        const frame = frameLayer(
            frames,
            `folio-tool-frame ${slotClass(mark)}`,
            FRAME_WEIGHT,
        );
        drawn!.addLayer(frame);
        drawnMarks.set(nodeOf(mark), { marker, halo: halos[index], frame });
    });
    restyle();
    const key = canvas.value?.id ?? null;
    if (!hasImage.value && markers.length > 0 && fitted !== key) {
        fitted = key;
        map.fitBounds(
            L.featureGroup(markers).getBounds().pad(NO_IMAGE_PADDING),
            { animate: false },
        );
    }
}

/** The frame of a mark at `level`, solid and tinted at the preview's weight while `preview` links it. */
function frameStyle(
    level: LinkedMark | undefined,
    preview: RelationLevel | undefined,
): L.PathOptions {
    const style: L.PathOptions = {
        weight: FRAME_WEIGHT,
        opacity: 1,
        dashArray: FRAME_DASH,
        fill: preview !== undefined,
        fillOpacity: preview ? PREVIEW_FILL[preview] : 0,
    };
    if (level === "self") {
        Object.assign(style, { weight: SELF_FRAME_WEIGHT, dashArray: "" });
    } else if (level === "direct") {
        Object.assign(style, { weight: LINKED_FRAME_WEIGHT, dashArray: "" });
    } else if (level === "evidence") {
        style.weight = LINKED_FRAME_WEIGHT;
    } else if (level === "none") {
        style.opacity = FADED_OPACITY;
    }
    if (preview) {
        Object.assign(style, {
            weight: PREVIEW_WEIGHT[preview],
            opacity: 1,
            dashArray: "",
        });
    }
    return style;
}

/** Shows each Component outline by how it stands to the focus and the preview, on the layers already drawn. */
function restyleOutlines(): void {
    for (const [node, layers] of drawnOutlines) {
        const level = linkedMarks.rel(node);
        const preview = linkedMarks.previewRel(node);
        const attributes = linkedMarks.focus(node);
        const lit = level === "self" || level === "direct";
        const hue = preview
            ? attributes.style?.["--hp"]
            : lit
              ? attributes.style?.["--h1"]
              : undefined;
        layers.outline.setStyle(
            preview
                ? {
                      opacity: 1,
                      weight: PREVIEW_WEIGHT[preview],
                      fillOpacity: PREVIEW_FILL[preview],
                  }
                : {
                      opacity: level === "none" ? FADED_OPACITY : 1,
                      weight: OUTLINE_WEIGHT,
                      fillOpacity: lit ? OUTLINE_TINT : 0,
                  },
        );
        layers.outline.eachLayer((layer) => {
            const path = (layer as L.Path).getElement?.();
            if (!(path instanceof SVGElement)) return;
            path.dataset.node = node;
            setData(path, "preview", preview);
            setProperty(path, "--frame-hue", hue);
        });
        const host = layers.label?.getElement();
        if (!host) continue;
        host.dataset.node = node;
        setData(host, "rel", level);
        setData(host, "preview", preview);
        setData(host, "slots", attributes["data-slots"]);
        setProperty(host, "--h1", lit ? attributes.style?.["--h1"] : undefined);
        setProperty(host, "--hp", attributes.style?.["--hp"]);
    }
}

/** Shows each mark and outline drawn by how its record stands to the focus and the preview, on the layers already drawn. */
function restyle(): void {
    restyleOutlines();
    for (const [node, layers] of drawnMarks) {
        const level = linkedMarks.rel(node);
        const preview = linkedMarks.previewRel(node);
        const attributes = linkedMarks.focus(node);
        const hue =
            (preview ? attributes.style?.["--hp"] : undefined) ??
            linkedMarks.hue(node) ??
            undefined;
        layers.frame.setStyle(frameStyle(level, preview));
        layers.frame.eachLayer((layer) => {
            const path = (layer as L.Path).getElement?.();
            if (!(path instanceof SVGElement)) return;
            setData(path, "preview", preview);
            setProperty(path, "--frame-hue", hue);
        });
        layers.halo.setStyle({
            opacity:
                level === "none" && !preview
                    ? FADED_OPACITY * HALO_OPACITY
                    : HALO_OPACITY,
        });
        layers.halo.eachLayer((layer) => {
            const path = (layer as L.Path).getElement?.();
            if (!(path instanceof SVGElement)) return;
            path.setAttribute("pathLength", "100");
            setData(path, "preview", preview);
            setProperty(path, "--frame-hue", hue);
        });
        const host = layers.marker?.getElement();
        if (!host) continue;
        host.dataset.node = node;
        setData(host, "rel", level);
        setData(host, "preview", preview);
        setData(host, "slots", attributes["data-slots"]);
        setProperty(host, "--h1", attributes.style?.["--h1"]);
        setProperty(host, "--hp", attributes.style?.["--hp"]);
    }
}

function setData(
    element: HTMLElement | SVGElement,
    name: string,
    value: string | undefined,
): void {
    if (value === undefined) delete element.dataset[name];
    else element.dataset[name] = value;
}

function setProperty(
    element: HTMLElement | SVGElement,
    name: string,
    value: string | undefined,
): void {
    if (value === undefined) element.style.removeProperty(name);
    else element.style.setProperty(name, value);
}

/** Frames the marks of the page the selection links. */
function fitRelated(): void {
    if (!map) return;
    const bounds = L.latLngBounds([]);
    for (const mark of relatedHere.value) {
        const layers = drawnMarks.get(nodeOf(mark));
        if (!layers) continue;
        if (layers.marker) bounds.extend(layers.marker.getLatLng());
        const frame = layers.frame.getBounds();
        if (frame.isValid()) bounds.extend(frame);
    }
    if (bounds.isValid()) {
        pageView = false;
        map.fitBounds(bounds.pad(RELATED_PADDING), { animate: false });
    }
}

function onReaderMove(): void {
    pageView = false;
}

function showFolio(canvasId: string): void {
    chosen.value = canvasId;
}

function onEnter(mark: FolioMark, event: PointerEvent): void {
    linkedMarks.enter(nodeOf(mark), event);
}

function showLabel(label: string): string {
    return interpolate($gettext("Show %{folio}"), { folio: label }, true);
}

function wholePage(): void {
    if (!map) return;
    pageView = true;
    fitPage(map, page);
}
</script>

<template>
    <div class="folio-tool">
        <div class="picker">
            <label :for="pickerId">
                <span>{{ $gettext("Folio") }}</span>
            </label>
            <div
                class="stepper"
                role="group"
                :aria-label="$gettext('Folio')"
            >
                <IconButton
                    data-action="previous-folio"
                    icon="chevron-left"
                    :label="$gettext('Previous folio')"
                    :disabled="position <= 0"
                    tip-align="start"
                    @click="step(-1)"
                />
                <select
                    :id="pickerId"
                    :value="row?.canvas ?? ''"
                    @change="onPick"
                >
                    <option
                        v-for="entry in props.canvases"
                        :key="entry.canvas"
                        :value="entry.canvas"
                    >
                        {{ entry.label }}
                    </option>
                </select>
                <IconButton
                    data-action="next-folio"
                    icon="chevron-right"
                    :label="$gettext('Next folio')"
                    :disabled="
                        position < 0 || position >= props.canvases.length - 1
                    "
                    tip-align="start"
                    @click="step(1)"
                />
            </div>
            <IconButton
                v-if="hasImage"
                data-action="whole-page"
                icon="search-minus"
                :label="$gettext('Whole page')"
                @click="wholePage"
            />
        </div>
        <UnavailableState
            v-if="documentRequest.status.value === 'error'"
            status="error"
            :hide-home="true"
            @retry="documentRequest.retry"
        />
        <UnavailableState
            v-else-if="documentRequest.status.value === 'unavailable'"
            status="unavailable"
            :hide-home="true"
            @retry="documentRequest.retry"
        />
        <p
            v-else-if="!payload"
            class="loading"
            role="status"
        >
            <LoadingSpinner />
            <span>{{ $gettext("Reading the document…") }}</span>
        </p>
        <div
            ref="host"
            class="stage"
            :hidden="!payload"
        >
            <div
                class="surface"
                @pointerdown="onReaderMove"
                @wheel.passive="onReaderMove"
                @keydown="onReaderMove"
            />
            <p
                v-if="payload && !hasImage"
                class="no-image"
                role="status"
            >
                <span>{{ $gettext("No image for this page.") }}</span>
            </p>
            <p
                v-else-if="pageFailed"
                class="no-image"
                role="status"
            >
                <span>{{
                    $gettext(
                        "Page image unavailable (the institution's IIIF server).",
                    )
                }}</span>
                <button
                    type="button"
                    class="retry"
                    @click="drawPage"
                >
                    <span>{{ $gettext("Retry") }}</span>
                </button>
            </p>
        </div>
        <template v-if="payload">
            <div
                v-if="linkedMarks.active.value"
                class="related"
            >
                <button
                    v-if="relatedHere.length > 0"
                    type="button"
                    class="fit"
                    @click="fitRelated"
                >
                    <span>{{ $gettext("Fit to related") }}</span>
                </button>
                <p
                    v-if="elsewhere.length > 0"
                    class="elsewhere"
                >
                    <span>{{ elsewhereText }}</span>
                    <button
                        v-for="entry in elsewhere.slice(0, SHOWN_ELSEWHERE)"
                        :key="entry.canvas"
                        type="button"
                        class="show"
                        @click="showFolio(entry.canvas)"
                    >
                        <span>{{ showLabel(entry.label) }}</span>
                    </button>
                </p>
            </div>
            <ul
                v-if="folioMarksShown.length > 0"
                class="marks"
                :aria-label="$gettext('Selection items on this folio')"
            >
                <li
                    v-for="mark in folioMarksShown"
                    :key="mark.id"
                    :data-rel="linkedMarks.rel(nodeOf(mark))"
                    :data-preview="linkedMarks.previewRel(nodeOf(mark))"
                    :style="linkedMarks.rowStyle(nodeOf(mark))"
                    @pointerenter="onEnter(mark, $event)"
                    @pointerleave="linkedMarks.leave($event)"
                >
                    <span
                        class="slot"
                        :class="slotClass(mark)"
                        :data-rel="linkedMarks.rel(mark.slots.map(slotNode))"
                        >{{ slotsText(mark) }}</span
                    >
                    <TechniqueCode
                        v-if="mark.technique"
                        :code="mark.technique.code"
                        :colour="mark.technique.colour"
                        size="small"
                    />
                    <button
                        type="button"
                        class="name ms-focus"
                        v-bind="linkedMarks.focus(nodeOf(mark))"
                        :lang="mark.name.lang"
                        :aria-pressed="linkedMarks.pressed(nodeOf(mark))"
                        @click="linkedMarks.toggle(nodeOf(mark))"
                    >
                        <FocusPip :node="nodeOf(mark)" />
                        <span>{{ mark.name.value }}</span>
                    </button>
                    <span
                        v-if="mark.kind === 'characterization'"
                        class="kind"
                        >{{ $gettext("Identified material") }}</span
                    >
                </li>
            </ul>
            <p
                v-else
                class="empty"
            >
                <span>{{
                    $gettext(
                        "No item of the Selection is placed on this folio.",
                    )
                }}</span>
            </p>
            <ul
                v-if="outlinesShown.length > 0"
                class="marks outlines"
                :aria-label="$gettext('Components outlined on this folio')"
            >
                <li
                    v-for="outline in outlinesShown"
                    :key="outline.id"
                    :data-rel="linkedMarks.rel(componentNode(outline.id))"
                    :data-preview="
                        linkedMarks.previewRel(componentNode(outline.id))
                    "
                    :style="linkedMarks.rowStyle(componentNode(outline.id))"
                    @pointerenter="
                        linkedMarks.enter(componentNode(outline.id), $event)
                    "
                    @pointerleave="linkedMarks.leave($event)"
                >
                    <span
                        class="outline-swatch"
                        aria-hidden="true"
                    />
                    <button
                        type="button"
                        class="name ms-focus"
                        v-bind="linkedMarks.focus(componentNode(outline.id))"
                        :lang="outline.name.lang"
                        :aria-pressed="
                            linkedMarks.pressed(componentNode(outline.id))
                        "
                        @click="linkedMarks.toggle(componentNode(outline.id))"
                    >
                        <FocusPip :node="componentNode(outline.id)" />
                        <span>{{ outline.name.value }}</span>
                    </button>
                    <span class="kind">{{ $gettext("Component") }}</span>
                </li>
            </ul>
        </template>
    </div>
</template>

<style scoped>
.folio-tool {
    display: grid;
    flex: 1 1 auto;
    grid-template-rows: auto minmax(12rem, 1fr) auto;
    gap: 0.5rem;
    min-block-size: 0;
}

.folio-tool .picker {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8125rem;
}

.folio-tool .stepper {
    display: inline-flex;
    align-items: center;
    gap: 0.125rem;
}

.folio-tool .picker select,
.folio-tool .picker button,
.folio-tool .no-image .retry {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
}

.folio-tool .picker button,
.folio-tool .no-image .retry {
    cursor: pointer;
}

.folio-tool select:focus-visible,
.folio-tool button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.folio-tool .loading {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--ink-muted);
}

.folio-tool .stage {
    position: relative;
    isolation: isolate;
    display: grid;
    min-block-size: 12rem;
    border-radius: var(--explorer-radius, 0.625rem);
    background: var(--bg-alt);
    overflow: hidden;
}

.folio-tool .stage[hidden] {
    display: none;
}

.folio-tool .surface {
    min-block-size: 12rem;
    background: var(--bg-alt);
}

.folio-tool .no-image {
    position: absolute;
    inset-block-end: 0.5rem;
    inset-inline-start: 0.5rem;
    z-index: 1000;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0;
    padding: 0.25rem 0.5rem;
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font-size: 0.8125rem;
}

.folio-tool .marks {
    display: grid;
    gap: var(--focus-room);
    margin: 0;
    padding: 0;
    list-style: none;
    font-size: 0.8125rem;
}

.folio-tool .marks li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--focus-room) 0.375rem;
}

.folio-tool .marks .slot {
    padding-inline: 0.375rem;
    border-radius: 0.25rem;
    background: var(--slot-fill);
    color: var(--slot-on);
    font: 600 0.75rem var(--font-mono);
}

.folio-tool .marks .kind,
.folio-tool .empty {
    color: var(--ink-muted);
}

.folio-tool :deep(.folio-tool-marker-host) {
    display: flex;
    justify-content: center;
    background: none;
    border: none;
}

.folio-tool :deep(.folio-tool-marker) {
    display: grid;
    flex: none;
    place-items: center;
    box-sizing: border-box;
    min-inline-size: 1.75rem;
    block-size: 1.75rem;
    padding-inline: 0.25rem;
    border: 0.125rem solid var(--surface);
    border-radius: 999rem;
    background: var(--slot-fill);
    color: var(--slot-on);
    font: 600 0.625rem var(--font-mono);
    white-space: nowrap;
}

.folio-tool :deep(.folio-tool-halo) {
    stroke: var(--surface);
}

.folio-tool :deep(.folio-tool-frame) {
    stroke: var(--frame-hue, var(--ink));
}

.folio-tool :deep(.folio-tool-outline) {
    fill: var(--frame-hue, transparent);
    stroke: var(--frame-hue, var(--ink-dim));
}

.folio-tool :deep(.folio-tool-outline-label-host) {
    background: none;
    border: none;
}

.folio-tool :deep(.folio-tool-outline-label) {
    display: inline-block;
    padding: 0 0.25rem;
    border-radius: 0.125rem;
    background: color-mix(in srgb, var(--surface) 85%, transparent);
    color: var(--ink-muted);
    font-size: 0.5625rem;
    white-space: nowrap;
}

.folio-tool
    :deep(
        .folio-tool-outline-label-host[data-rel="none"]
            .folio-tool-outline-label
    ) {
    opacity: var(--linked-fade, 0.35);
}

.folio-tool
    :deep(
        .folio-tool-outline-label-host:is(
                [data-rel="self"],
                [data-rel="direct"]
            )
            .folio-tool-outline-label
    ) {
    color: var(--h1, var(--ink));
}

.folio-tool .outlines .outline-swatch {
    inline-size: 0.75rem;
    block-size: 0.5rem;
    border: 0.09375rem solid var(--ink-dim);
    border-radius: 0.125rem;
}

.folio-tool
    .outlines
    li:is([data-rel="self"], [data-rel="direct"])
    .outline-swatch {
    border-color: var(--h1, var(--ink-dim));
    background: color-mix(in srgb, var(--h1, var(--focus-1)) 8%, transparent);
}

.folio-tool :deep(.folio-tool-marker-host[data-rel="none"] .folio-tool-marker) {
    background: color-mix(
        in srgb,
        var(--slot-fill) calc(var(--linked-fade, 0.35) * 100%),
        var(--surface)
    );
    color: var(--ink);
}

.folio-tool
    :deep(
        .folio-tool-marker-host[data-rel="none"]
            .folio-tool-marker:is(.item-ring, .item-ring-dot)
    ) {
    border-color: color-mix(
        in srgb,
        var(--slot-fill) calc(var(--linked-fade, 0.35) * 100%),
        var(--surface)
    );
    background: var(--surface);
}

.folio-tool :deep(.folio-tool-marker-host[data-rel="self"] .folio-tool-marker) {
    outline: 0.1875rem solid var(--h1, var(--focus-1));
    outline-offset: 0.0625rem;
}

.folio-tool
    :deep(.folio-tool-marker-host[data-rel="direct"] .folio-tool-marker) {
    box-shadow: 0 0 0 0.125rem var(--h1, var(--focus-1));
}

.folio-tool
    :deep(.folio-tool-marker-host[data-rel="evidence"] .folio-tool-marker) {
    outline: 0.0625rem solid var(--h1, var(--focus-1));
    outline-offset: 0.0625rem;
}

.folio-tool :deep(.folio-tool-marker-host[data-preview] .folio-tool-marker) {
    outline: 0.0625rem solid var(--hp, var(--focus-1));
    outline-offset: 0.125rem;
}

.folio-tool
    :deep(.folio-tool-marker-host[data-preview="self"] .folio-tool-marker) {
    outline-width: 0.125rem;
}

.folio-tool .related {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8125rem;
}

.folio-tool .related .elsewhere {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin: 0;
}

.folio-tool .related button {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.folio-tool .marks .name {
    --r: 0.375rem;
    --link-pip: 0.8125rem;
    min-block-size: 1.5rem;
    padding: 0.25rem 0.375rem;
    border: 0.0625rem solid transparent;
    border-radius: 0.375rem;
    background: none;
    color: inherit;
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.folio-tool .marks .name:hover {
    border-color: var(--border-hover);
}

.folio-tool .marks li {
    position: relative;
    padding-inline-start: 0.5rem;
    border-radius: 0.375rem;
    transition:
        background-color var(--dur-med, 260ms),
        color var(--dur-med, 260ms);
}

.folio-tool .marks li::before {
    position: absolute;
    inset-block: 0;
    inset-inline-start: 0;
    inline-size: 0;
    background: var(--bar, var(--focus-1));
    content: "";
    transition: inline-size var(--dur-med, 260ms) var(--ease-out-expo);
}

.folio-tool
    .marks
    li:is([data-rel="self"], [data-rel="direct"], [data-rel="evidence"]) {
    background: color-mix(
        in srgb,
        var(--h1, var(--focus-1)) 6%,
        var(--surface)
    );
}

.folio-tool .marks li[data-rel="self"]::before {
    inline-size: 0.25rem;
}

.folio-tool .marks li[data-rel="direct"]::before {
    inline-size: 0.1875rem;
}

.folio-tool .marks li[data-rel="evidence"]::before {
    inline-size: 0.0625rem;
}

.folio-tool .marks li[data-rel="none"] {
    color: var(--ink-muted);
}

.folio-tool .marks li[data-preview] {
    background: color-mix(
        in srgb,
        var(--hp, var(--focus-1)) 5%,
        var(--surface)
    );
}

.folio-tool .marks li[data-preview="evidence"] {
    background: color-mix(
        in srgb,
        var(--hp, var(--focus-1)) 3%,
        var(--surface)
    );
}

.folio-tool :deep(.folio-tool-marker.item-ring),
.folio-tool :deep(.folio-tool-marker.item-ring-dot) {
    position: relative;
    border-color: var(--slot-fill);
    background: var(--surface);
    color: var(--ink);
}

.folio-tool :deep(.folio-tool-marker.item-ring-dot)::before {
    content: "";
    position: absolute;
    inset-block-start: -0.25rem;
    inset-inline-end: -0.25rem;
    inline-size: 0.5rem;
    block-size: 0.5rem;
    border: 0.0625rem solid var(--surface);
    border-radius: 50%;
    background: var(--slot-fill);
}

.folio-tool .marks :is(.item-ring, .item-ring-dot) {
    background: var(--surface);
    box-shadow: inset 0 0 0 0.125rem var(--slot-fill);
    color: var(--ink);
}

.folio-tool
    :deep(
        .folio-tool-frame:is(
                .slot-1,
                .slot-2,
                .slot-3,
                .slot-4,
                .slot-5,
                .slot-6,
                .slot-7,
                .slot-8,
                .slot-9,
                .slot-10,
                .slot-11,
                .slot-12
            )
    ) {
    stroke: var(--slot-fill);
}

.folio-tool :deep(.folio-tool-frame[data-preview]),
.folio-tool :deep(.folio-tool-outline[data-preview]) {
    fill: var(--frame-hue, var(--focus-1));
    stroke: color-mix(
        in srgb,
        var(--frame-hue, var(--focus-1)) 80%,
        transparent
    );
}

.folio-tool :deep(.folio-tool-frame[data-preview="self"]),
.folio-tool :deep(.folio-tool-outline[data-preview="self"]) {
    filter: drop-shadow(
        0 0 0.1875rem
            color-mix(
                in srgb,
                var(--frame-hue, var(--focus-1)) 45%,
                transparent
            )
    );
}

@media (prefers-reduced-motion: no-preference) {
    .folio-tool :deep(.folio-tool-halo[data-preview="self"]) {
        animation: folio-tool-orbit 1.4s cubic-bezier(0.45, 0, 0.25, 1) 1;
    }
}

@keyframes folio-tool-orbit {
    from {
        stroke: color-mix(in srgb, var(--frame-hue, var(--focus-1)) 40%, #fff);
        stroke-dasharray: 14 86;
        stroke-dashoffset: 100;
        opacity: 1;
    }

    90% {
        stroke: color-mix(in srgb, var(--frame-hue, var(--focus-1)) 40%, #fff);
        stroke-dasharray: 14 86;
        opacity: 1;
    }

    to {
        stroke: color-mix(in srgb, var(--frame-hue, var(--focus-1)) 40%, #fff);
        stroke-dasharray: 14 86;
        stroke-dashoffset: 0;
        opacity: 0;
    }
}
</style>
