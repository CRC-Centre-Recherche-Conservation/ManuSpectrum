<script setup lang="ts">
import {
    computed,
    onBeforeUnmount,
    onMounted,
    ref,
    useTemplateRef,
    watch,
} from "vue";
import L from "leaflet";
import "leaflet-iiif";
import "leaflet.markercluster";
import "leaflet-side-by-side";
import { useGettext } from "vue3-gettext";
import { infoJsonUrl } from "utils/iiif-image";
import { stackSmallestOnTop } from "utils/leaflet-stack";

import {
    markedZones,
    shapeCentre,
    shapeFeature,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import {
    curtainable,
    overlayPane,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import {
    nextId,
    readingOrder,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/roving.ts";
import { techniqueKey } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import {
    folioLayerOf,
    viewerFor,
} from "@/manuspectrum/pages/AnalysisExplorer/viewers/registry.ts";

import type {
    Annotation,
    CharacterizationSummary,
    DocumentCanvas,
    SampleSummary,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { FolioOverlay } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import type { TechniqueStyle } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import type {
    Focus,
    FolioView,
    LayerToggles,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const CLUSTER_RADIUS = 36;
const MAX_ZOOM = 8;
const INITIAL_ZOOM = 2;
const MARKER_SIZE = 28;
const CLUSTER_SIZE = 32;
const MATERIAL_POINT_RADIUS = 8;
const NO_IMAGE_PADDING = 0.5;
const HATCH_ID = "ms-folio-hatch";
const SVG_NS = "http://www.w3.org/2000/svg";
const CLUSTER_PREFIX = "cluster:";
const SAMPLE_PREFIX = "sample:";

/** The leaflet-iiif 3.0.0 state the folio reads: the info.json request, the image sizes it yields, the tile container. */
type IiifLayer = L.TileLayer & {
    _infoPromise?: Promise<unknown> | null;
    _imageSizes?: unknown[];
    _container?: HTMLElement;
};

const props = withDefaults(
    defineProps<{
        canvas: DocumentCanvas | null;
        annotations: Annotation[];
        characterizations: CharacterizationSummary[];
        styles: Map<string, TechniqueStyle>;
        focus: Focus | null;
        slots: Map<string, string[]>;
        lit: ReadonlySet<string> | null;
        dimmedMaterials: ReadonlySet<string>;
        layers: LayerToggles;
        view: FolioView;
        samples: SampleSummary[];
        overlays?: FolioOverlay[];
        curtain?: string | null;
    }>(),
    { overlays: () => [], curtain: null },
);
const emit = defineEmits<{ select: [focus: Focus] }>();
defineExpose({ focusTarget });

const { $gettext, interpolate } = useGettext();
const host = useTemplateRef<HTMLDivElement>("host");

const active = ref<string | null>(null);
// Leaflet objects live outside Vue reactivity.
let map: L.Map | null = null;
let page: IiifLayer | null = null;
let cluster: L.MarkerClusterGroup | null = null;
let frames: L.GeoJSON | null = null;
let materials: L.GeoJSON | null = null;
let sampleZones: L.GeoJSON | null = null;
let order: string[] = [];
let openedGroup: Set<string> | null = null;
// An imageless page is fitted to its markers once; later redraws keep the reader's view.
let fittedCanvas: string | null | undefined;
const markers = new Map<string, L.Marker>();
const targets = new Map<string, L.Marker>();
const images = new Map<string, L.ImageOverlay>();
let sideBySide: L.SideBySide | null = null;

const hasImage = computed((): boolean => Boolean(props.canvas?.image.service));

watch(() => props.canvas?.id, drawPage);
watch(
    () => [
        props.annotations,
        props.characterizations,
        props.styles,
        props.slots,
        props.layers,
        props.dimmedMaterials,
        props.view,
        props.samples,
        props.lit,
    ],
    drawMarks,
);
watch(() => props.focus, refreshStates);
watch(() => [props.overlays, props.curtain], drawOverlays);

onMounted(() => {
    const surface = host.value?.querySelector<HTMLElement>(".surface");
    if (!surface) return;
    map = L.map(surface, {
        crs: L.CRS.Simple,
        zoomControl: false,
        attributionControl: false,
        keyboard: false,
        minZoom: 0,
        maxZoom: MAX_ZOOM,
        zoomSnap: 0.25,
    });
    map.setView([0, 0], INITIAL_ZOOM);
    stackSmallestOnTop(map);
    map.on("zoomend moveend", computeTargets);
    drawPage();
    drawMarks();
    drawOverlays();
});

onBeforeUnmount(() => {
    sideBySide?.remove();
    sideBySide = null;
    images.clear();
    map?.remove();
    map = null;
});

function markerLabel(
    annotation: Annotation,
    style: TechniqueStyle | undefined,
): string {
    const parts = [
        annotation.name.value,
        style?.label.value ?? $gettext("Analysis"),
    ];
    const slots = props.slots.get(annotation.analysis) ?? [];
    if (slots.length > 0) {
        parts.push(
            interpolate(
                $gettext("in the Selection as %{slots}"),
                { slots: slots.join(", ") },
                true,
            ),
        );
    }
    if (annotation.unpublished) parts.push($gettext("Draft"));
    return parts.join(", ");
}

function markerIcon(annotation: Annotation): L.DivIcon {
    const style = props.styles.get(techniqueKey(annotation.technique));
    const element = document.createElement("span");
    element.id = `folio-marker-${annotation.analysis}`;
    element.dataset.target = annotation.analysis;
    element.setAttribute("role", "button");
    element.setAttribute("aria-label", markerLabel(annotation, style));
    element.tabIndex = -1;
    element.className = [
        "folio-marker",
        style?.colour
            ? `folio-marker--tech-${style.colour}`
            : "folio-marker--ink",
    ].join(" ");
    const code = document.createElement("span");
    code.className = "code";
    code.textContent = style?.code ?? "?";
    element.append(code);
    const slots = props.slots.get(annotation.analysis) ?? [];
    if (slots.length > 0) {
        const badge = document.createElement("span");
        badge.className = "slot";
        badge.textContent = slots.join(" ");
        element.append(badge);
    }
    if (annotation.unpublished) {
        const draft = document.createElement("span");
        draft.className = "draft";
        draft.setAttribute("aria-hidden", "true");
        element.append(draft);
    }
    return L.divIcon({
        html: element,
        className: "folio-marker-host",
        iconSize: [MARKER_SIZE, MARKER_SIZE],
    });
}

/** The group's icon host takes no tab stop: the roving `span` inside is the target. */
function clusterIcon(group: L.MarkerCluster): L.DivIcon {
    group.options.keyboard = false;
    const count = group.getChildCount();
    const element = document.createElement("span");
    element.dataset.target = `${CLUSTER_PREFIX}${L.stamp(group)}`;
    element.setAttribute("role", "button");
    element.setAttribute(
        "aria-label",
        interpolate(
            props.view === "samples"
                ? $gettext("%{n} samples here, zoom in")
                : $gettext("%{n} analyses here, zoom in"),
            { n: count },
            true,
        ),
    );
    element.tabIndex = -1;
    element.className = "folio-cluster";
    element.textContent = String(count);
    return L.divIcon({
        html: element,
        className: "folio-marker-host",
        iconSize: [CLUSTER_SIZE, CLUSTER_SIZE],
    });
}

function materialLabel(summary: CharacterizationSummary): HTMLElement {
    const element = document.createElement("span");
    element.textContent =
        summary.materials.map((entry) => entry.value.label.value).join(", ") ||
        summary.name.value;
    return element;
}

/**
 * An analysis is drawn in the analyses view, and in the identified-materials
 * view when it is evidence of the open material; its layer toggle applies in
 * both.
 */
function isShown(annotation: Annotation): boolean {
    const inView =
        props.view === "analyses" ||
        (props.view === "characterizations" &&
            (props.lit?.has(annotation.analysis) ?? false));
    return inView && props.layers[folioLayerOf(annotation.dataKind)];
}

function sampleIcon(sample: SampleSummary): L.DivIcon {
    const element = document.createElement("span");
    element.id = `folio-sample-${sample.id}`;
    element.dataset.target = `${SAMPLE_PREFIX}${sample.id}`;
    element.setAttribute("role", "button");
    const parts = [sample.name.value, $gettext("Sample")];
    if (sample.unpublished) parts.push($gettext("Draft"));
    element.setAttribute("aria-label", parts.join(", "));
    element.tabIndex = -1;
    element.className = "folio-sample";
    if (sample.unpublished) {
        const draft = document.createElement("span");
        draft.className = "draft";
        draft.setAttribute("aria-hidden", "true");
        element.append(draft);
    }
    return L.divIcon({
        html: element,
        className: "folio-marker-host",
        iconSize: [MARKER_SIZE, MARKER_SIZE],
    });
}

function ensureHatch(): void {
    const svg = map?.getPanes().overlayPane.querySelector("svg");
    if (!svg || svg.querySelector(`#${HATCH_ID}`)) return;
    const defs = document.createElementNS(SVG_NS, "defs");
    const pattern = document.createElementNS(SVG_NS, "pattern");
    pattern.id = HATCH_ID;
    pattern.setAttribute("patternUnits", "userSpaceOnUse");
    pattern.setAttribute("width", "8");
    pattern.setAttribute("height", "8");
    pattern.setAttribute("patternTransform", "rotate(45)");
    const line = document.createElementNS(SVG_NS, "line");
    line.setAttribute("x1", "0");
    line.setAttribute("y1", "0");
    line.setAttribute("x2", "0");
    line.setAttribute("y2", "8");
    line.setAttribute("class", "folio-hatch-line");
    pattern.append(line);
    defs.append(pattern);
    svg.prepend(defs);
}

/**
 * Lays the page's IIIF image once leaflet-iiif has read its info.json, if the
 * page is still the one shown. leaflet-iiif lays its tiles only after that
 * read (never, when the image host refuses it), and GridLayer.onRemove throws
 * on a layer whose tiles are not laid: an unread page never reaches the map,
 * and a page removed in the instant between its addition and its tiles is
 * dropped without calling GridLayer.onRemove.
 */
function drawPage(): void {
    if (!map) return;
    if (page && map.hasLayer(page)) map.removeLayer(page);
    page = null;
    const service = props.canvas?.image.service;
    if (!service) return;
    const next = L.tileLayer.iiif(infoJsonUrl(service), {
        fitBounds: true,
        setMaxBounds: false,
    }) as IiifLayer;
    const onRemove = next.onRemove;
    next.onRemove = (from: L.Map) =>
        next._container ? onRemove.call(next, from) : next;
    page = next;
    void Promise.resolve(next._infoPromise).then(() => {
        if (map && page === next && next._imageSizes) map.addLayer(next);
    });
}

function drawMarks(): void {
    if (!map) return;
    openedGroup = null;
    cluster?.remove();
    frames?.remove();
    materials?.remove();
    sampleZones?.remove();
    markers.clear();

    cluster = L.markerClusterGroup({
        maxClusterRadius: CLUSTER_RADIUS,
        showCoverageOnHover: false,
        spiderfyOnMaxZoom: true,
        removeOutsideVisibleBounds: false,
        iconCreateFunction: clusterIcon,
    });
    for (const annotation of markedZones(props.annotations)) {
        if (!isShown(annotation)) continue;
        const centre = shapeCentre(annotation.shape);
        if (!centre) continue;
        const marker = L.marker(centre, {
            icon: markerIcon(annotation),
            keyboard: false,
        });
        marker.on("click", () => activate(annotation.analysis));
        markers.set(annotation.analysis, marker);
    }
    const shownSamples = props.view === "samples" ? props.samples : [];
    for (const sample of shownSamples) {
        const centre = sample.zone ? shapeCentre(sample.zone.shape) : null;
        if (!centre) continue;
        const target = `${SAMPLE_PREFIX}${sample.id}`;
        const marker = L.marker(centre, {
            icon: sampleIcon(sample),
            keyboard: false,
        });
        marker.on("click", () => activate(target));
        markers.set(target, marker);
    }
    const frameFeatures = [];
    for (const annotation of props.annotations) {
        if (
            !isShown(annotation) ||
            viewerFor(annotation.dataKind).folio !== "frame" ||
            annotation.shape.type === "point"
        ) {
            continue;
        }
        const style = props.styles.get(techniqueKey(annotation.technique));
        const feature = shapeFeature(annotation.shape, {
            analysis: annotation.analysis,
            colour: style?.colour ?? null,
        });
        if (feature) frameFeatures.push(feature);
    }
    cluster.addLayers([...markers.values()]);
    cluster.on("animationend spiderfied unspiderfied", settleGroups);
    map.addLayer(cluster);

    frames = L.geoJSON(frameFeatures, {
        style: (feature) => ({
            className: `folio-frame${feature?.properties.colour ? ` folio-frame--tech-${feature.properties.colour}` : ""}`,
            dashArray: "4 4",
            weight: 2,
            fill: false,
            interactive: false,
        }),
    }).addTo(map);

    sampleZones = L.geoJSON(
        shownSamples.flatMap((sample) => {
            const feature =
                sample.zone && sample.zone.shape.type !== "point"
                    ? shapeFeature(sample.zone.shape, { id: sample.id })
                    : null;
            return feature ? [feature] : [];
        }),
        {
            style: () => ({
                className: "folio-sample-zone",
                weight: 2,
                fill: false,
                interactive: false,
            }),
        },
    ).addTo(map);

    const materialFeatures =
        props.view === "characterizations" && props.layers.characterizations
            ? props.characterizations.flatMap((summary) => {
                  const feature = summary.zone
                      ? shapeFeature(summary.zone.shape, { id: summary.id })
                      : null;
                  return feature ? [feature] : [];
              })
            : [];
    materials = L.geoJSON(materialFeatures, {
        pointToLayer: (_feature, latlng) =>
            L.circleMarker(latlng, { radius: MATERIAL_POINT_RADIUS }),
        style: (feature) => ({
            className: `folio-material${props.dimmedMaterials.has(String(feature?.properties.id)) ? " is-dimmed" : ""}`,
            weight: 2,
        }),
        onEachFeature: (feature, layer) => {
            const id = String(feature.properties.id);
            const summary = props.characterizations.find(
                (entry) => entry.id === id,
            );
            if (summary) {
                layer.bindTooltip(materialLabel(summary), {
                    permanent: true,
                    direction: "center",
                    className: "folio-material-label",
                });
            }
            layer.on("click", () =>
                emit("select", { kind: "characterization", id }),
            );
        },
    }).addTo(map);
    ensureHatch();

    if (
        !hasImage.value &&
        markers.size > 0 &&
        fittedCanvas !== (props.canvas?.id ?? null)
    ) {
        fittedCanvas = props.canvas?.id ?? null;
        map.fitBounds(
            L.featureGroup([...markers.values()])
                .getBounds()
                .pad(NO_IMAGE_PADDING),
            { animate: false },
        );
    }
    computeTargets();
}

/**
 * Adds, updates and removes the laid layers by key. The curtain clips the one
 * named by `curtain`; one curtain control lives while a layer is curtained, so
 * its divider keeps its place when the opacity, the curtained layer or the
 * document payload changes.
 */
function drawOverlays(): void {
    if (!map) return;
    const wanted = new Set(props.overlays.map((overlay) => overlay.key));
    for (const [key, layer] of images) {
        if (!wanted.has(key)) {
            layer.remove();
            images.delete(key);
        }
    }
    for (const overlay of props.overlays) {
        const existing = images.get(overlay.key);
        if (existing) {
            existing.setOpacity(overlay.opacity);
            existing.setBounds(L.latLngBounds(overlay.bounds));
        } else {
            const pane = overlayPane(map, overlay.key);
            images.set(
                overlay.key,
                curtainable(
                    L.imageOverlay(overlay.url, overlay.bounds, {
                        opacity: overlay.opacity,
                        className: "folio-overlay",
                        alt: overlay.label,
                        pane,
                    }).addTo(map),
                    map.getPane(pane)!,
                ),
            );
        }
    }
    const under = props.curtain ? images.get(props.curtain) : undefined;
    if (!under) {
        sideBySide?.remove();
        sideBySide = null;
    } else if (sideBySide) {
        sideBySide.setRightLayers(under);
    } else {
        sideBySide = L.control
            .sideBySide([], under)
            .addTo(map)
            .on("rightlayerremove", unclip);
        (
            sideBySide as L.SideBySide & { _range?: HTMLElement }
        )._range?.setAttribute("aria-label", $gettext("Curtain position"));
    }
}

/** A layer that leaves the curtain keeps no clip: its pane may be laid again without it. */
function unclip(event: L.LeafletEvent): void {
    const { layer } = event as L.LeafletEvent & {
        layer: { getContainer?: () => HTMLElement | undefined };
    };
    const container = layer.getContainer?.();
    if (container) container.style.clip = "";
}

/** The id of the marker, or of the marker group, that shows an analysis or a sample (`sample:<id>`) now; null when neither is on the map. */
function visibleTargetOf(id: string): string | null {
    const marker = markers.get(id);
    const parent = marker ? cluster?.getVisibleParent(marker) : null;
    if (!marker || !parent) return null;
    return parent === marker ? id : `${CLUSTER_PREFIX}${L.stamp(parent)}`;
}

/** The markers and marker groups the reader can reach now, in reading order. */
function computeTargets(): void {
    targets.clear();
    for (const [id, marker] of markers) {
        const target = visibleTargetOf(id);
        const parent = cluster?.getVisibleParent(marker);
        if (target !== null && parent) targets.set(target, parent);
    }
    order = readingOrder(
        [...targets].map(([id, layer]) => {
            const { lat, lng } = layer.getLatLng();
            return { id, lat, lng };
        }),
    );
    if (active.value === null || !targets.has(active.value)) {
        active.value = order[0] ?? null;
    }
    refreshStates();
}

function targetElement(id: string): HTMLElement | null {
    return (
        host.value?.querySelector<HTMLElement>(`[data-target="${id}"]`) ?? null
    );
}

/** Classes and tab stops follow focus, evidence and filters without redrawing the markers. */
function refreshStates(): void {
    for (const sample of props.samples) {
        targetElement(`${SAMPLE_PREFIX}${sample.id}`)?.classList.toggle(
            "is-focused",
            props.focus?.kind === "sample" && props.focus.id === sample.id,
        );
    }
    for (const annotation of props.annotations) {
        const element = targetElement(annotation.analysis);
        if (!element) continue;
        const lit = props.lit?.has(annotation.analysis) ?? false;
        element.classList.toggle(
            "is-dimmed",
            !annotation.match || (props.lit !== null && !lit),
        );
        element.classList.toggle("is-lit", lit);
        element.classList.toggle(
            "is-focused",
            props.focus?.kind === "analysis" &&
                props.focus.id === annotation.analysis,
        );
    }
    for (const id of order) {
        const element = targetElement(id);
        if (element) element.tabIndex = id === active.value ? 0 : -1;
    }
}

function activate(id: string): void {
    if (id.startsWith(CLUSTER_PREFIX)) {
        openGroup(id);
        return;
    }
    active.value = id;
    if (id.startsWith(SAMPLE_PREFIX)) {
        emit("select", { kind: "sample", id: id.slice(SAMPLE_PREFIX.length) });
        return;
    }
    emit("select", { kind: "analysis", id });
}

/**
 * Opens a marker group the way a click does: markercluster zooms to it, or
 * spreads its markers when they stay grouped at the last zoom. The first
 * target of the group then takes the keyboard focus.
 */
function openGroup(id: string): void {
    const group = targets.get(id) as unknown as L.MarkerCluster | undefined;
    if (!group || !cluster) return;
    const children = new Set<L.Marker>(group.getAllChildMarkers());
    openedGroup = new Set(
        [...markers]
            .filter(([, marker]) => children.has(marker))
            .map(([target]) => target),
    );
    // The group turns a click carrying a cluster into its `clusterclick`.
    cluster.fire("click", { layer: group });
}

/** Targets follow markercluster's regrouping; after `openGroup` the first target of the opened group takes the focus. */
function settleGroups(): void {
    computeTargets();
    if (!openedGroup) return;
    const opened = [...openedGroup];
    openedGroup = null;
    const first = order.find((target) =>
        opened.some((analysis) => visibleTargetOf(analysis) === target),
    );
    if (first) moveTo(first);
}

function moveTo(id: string): void {
    active.value = id;
    refreshStates();
    targetElement(id)?.focus();
}

function onKeydown(event: KeyboardEvent): void {
    const element = (event.target as HTMLElement).closest<HTMLElement>(
        "[data-target]",
    );
    const id = element?.dataset.target;
    if (!id) return;
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activate(id);
        return;
    }
    const next = nextId(order, id, event.key);
    if (next === null) return;
    event.preventDefault();
    moveTo(next);
}

/** Puts the keyboard focus on the marker of an analysis or a sample (`sample:<id>`), or on the marker group that holds it. */
function focusTarget(id: string): void {
    const target = visibleTargetOf(id);
    if (target !== null && targets.has(target)) moveTo(target);
}

function zoomIn(): void {
    openedGroup = null;
    map?.zoomIn();
}

function zoomOut(): void {
    openedGroup = null;
    map?.zoomOut();
}

function wholePage(): void {
    openedGroup = null;
    if (page && map?.hasLayer(page) && "_fitBounds" in page) {
        // leaflet-iiif fits the whole image with this private method.
        (page as unknown as { _fitBounds: () => void })._fitBounds();
    } else if (markers.size > 0) {
        map?.fitBounds(
            L.featureGroup([...markers.values()])
                .getBounds()
                .pad(NO_IMAGE_PADDING),
        );
    }
}
</script>

<template>
    <div
        ref="host"
        class="folio"
        role="group"
        :aria-label="$gettext('Page and its analyses')"
        @keydown="onKeydown"
    >
        <div class="controls">
            <button
                type="button"
                class="control"
                @click="zoomIn"
            >
                <span>{{ $gettext("Zoom in") }}</span>
            </button>
            <button
                type="button"
                class="control"
                @click="zoomOut"
            >
                <span>{{ $gettext("Zoom out") }}</span>
            </button>
            <button
                type="button"
                class="control"
                @click="wholePage"
            >
                <span>{{ $gettext("Whole page") }}</span>
            </button>
        </div>
        <p
            v-if="!hasImage"
            class="no-image"
            role="status"
        >
            <span>{{ $gettext("No image for this page.") }}</span>
        </p>
        <div class="surface"></div>
    </div>
</template>

<style scoped>
.folio {
    position: relative;
    display: grid;
    grid-template-rows: auto 1fr;
    min-block-size: 28rem;
    background: var(--stage);
    border-radius: 0.5rem;
    overflow: hidden;
}

.folio .surface {
    min-block-size: 28rem;
    background: var(--stage);
}

.folio .controls {
    display: flex;
    gap: 0.25rem;
    padding: 0.5rem;
    background: var(--surface);
}

.folio .control {
    min-block-size: 2.75rem;
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.folio .control:focus-visible,
.folio :deep([data-target]:focus-visible) {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.folio .no-image {
    position: absolute;
    inset-block-start: 4rem;
    inset-inline: 1rem;
    z-index: 500;
    padding: 0.5rem 0.75rem;
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
}

.folio :deep(.folio-marker-host) {
    background: none;
    border: none;
}

.folio :deep(.folio-marker) {
    position: relative;
    display: grid;
    place-items: center;
    inline-size: 1.75rem;
    block-size: 1.75rem;
    border: 0.125rem solid var(--surface);
    border-radius: 50%;
    background: var(--ink);
    color: var(--stage);
    font: 600 0.75rem var(--font-body);
    cursor: pointer;
}

.folio :deep(.folio-marker--tech-1) {
    background: var(--tech-1);
}

.folio :deep(.folio-marker--tech-2) {
    background: var(--tech-2);
}

.folio :deep(.folio-marker--tech-3) {
    background: var(--tech-3);
}

.folio :deep(.folio-marker--tech-4) {
    background: var(--tech-4);
}

.folio :deep(.folio-marker--tech-5) {
    background: var(--tech-5);
}

.folio :deep(.folio-marker--tech-6) {
    background: var(--tech-6);
}

.folio :deep(.folio-marker--ink) {
    background: var(--surface);
    color: var(--ink);
}

.folio :deep(.folio-marker .slot) {
    position: absolute;
    inset-block-start: -0.75rem;
    inset-inline-start: 1.25rem;
    padding: 0 0.25rem;
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: 600 0.625rem var(--font-mono);
    white-space: nowrap;
}

.folio :deep(.folio-marker .draft) {
    position: absolute;
    inset-block-end: -0.125rem;
    inset-inline-end: -0.125rem;
    inline-size: 0.5rem;
    block-size: 0.5rem;
    border: 0.0625rem solid var(--surface);
    border-radius: 50%;
    background: var(--accent-text);
}

.folio :deep(.folio-marker.is-dimmed),
.folio :deep(.folio-material.is-dimmed) {
    opacity: 0.35;
}

.folio :deep(.folio-marker.is-lit),
.folio :deep(.folio-marker.is-focused) {
    box-shadow: 0 0 0 0.25rem
        color-mix(in srgb, var(--surface) 60%, transparent);
}

.folio :deep(.folio-sample) {
    position: relative;
    display: block;
    inline-size: 1.25rem;
    block-size: 1.25rem;
    margin: 0.25rem;
    border: 0.1875rem solid var(--ink);
    border-radius: 0.125rem;
    background: var(--surface);
    cursor: pointer;
}

.folio :deep(.folio-sample .draft) {
    position: absolute;
    inset-block-end: -0.375rem;
    inset-inline-end: -0.375rem;
    inline-size: 0.5rem;
    block-size: 0.5rem;
    border: 0.0625rem solid var(--surface);
    border-radius: 50%;
    background: var(--accent-text);
}

.folio :deep(.folio-sample.is-focused) {
    box-shadow: 0 0 0 0.25rem
        color-mix(in srgb, var(--surface) 60%, transparent);
}

.folio :deep(.folio-sample-zone) {
    stroke: var(--ink);
}

.folio :deep(.folio-cluster) {
    display: grid;
    place-items: center;
    inline-size: 2rem;
    block-size: 2rem;
    border: 0.125rem solid var(--surface);
    border-radius: 50%;
    background: var(--surface);
    color: var(--ink);
    font: 600 0.75rem var(--font-mono);
    cursor: pointer;
}

.folio :deep(.folio-frame) {
    stroke: var(--surface);
}

.folio :deep(.folio-frame--tech-1) {
    stroke: var(--tech-1);
}

.folio :deep(.folio-frame--tech-2) {
    stroke: var(--tech-2);
}

.folio :deep(.folio-frame--tech-3) {
    stroke: var(--tech-3);
}

.folio :deep(.folio-frame--tech-4) {
    stroke: var(--tech-4);
}

.folio :deep(.folio-frame--tech-5) {
    stroke: var(--tech-5);
}

.folio :deep(.folio-frame--tech-6) {
    stroke: var(--tech-6);
}

.folio :deep(.folio-material) {
    stroke: var(--accent-text);
    fill: url(#ms-folio-hatch);
    fill-opacity: 1;
    cursor: pointer;
}

.folio :deep(.folio-hatch-line) {
    stroke: var(--accent-text);
    stroke-width: 2;
}

.folio :deep(.folio-material-label) {
    background: var(--surface);
    color: var(--ink);
    font: 0.75rem var(--font-body);
    border: none;
    box-shadow: none;
}

.folio :deep(.folio-overlay) {
    image-rendering: pixelated;
}

@media (prefers-reduced-motion: reduce) {
    .folio :deep(.leaflet-zoom-anim .leaflet-zoom-animated) {
        transition: none;
    }
}
</style>
