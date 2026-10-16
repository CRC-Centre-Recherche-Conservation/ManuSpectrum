<script setup lang="ts">
import {
    computed,
    inject,
    nextTick,
    onMounted,
    ref,
    shallowRef,
    useTemplateRef,
    watch,
} from "vue";
import { useMediaQuery } from "@vueuse/core";
import Drawer from "primevue/drawer";
import { useGettext } from "vue3-gettext";

import BusyStatus from "@/manuspectrum/pages/AnalysisExplorer/components/BusyStatus.vue";
import HelpTip from "@/manuspectrum/pages/AnalysisExplorer/components/HelpTip.vue";
import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import FocusSlotDot from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusSlotDot.vue";
import RailPanel from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/RailPanel.vue";
import MapPanel from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/MapPanel.vue";
import MapStage from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/MapStage.vue";
import MapTimeline from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/MapTimeline.vue";
import MaterialsControl from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/MaterialsControl.vue";
import PlaceList from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/PlaceList.vue";
import SmallMultiples from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/SmallMultiples.vue";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import { useActiveFilters } from "@/manuspectrum/pages/AnalysisExplorer/composables/useActiveFilters.ts";
import {
    exportHref,
    useEvents,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useEvents.ts";
import { useEventLabels } from "@/manuspectrum/pages/AnalysisExplorer/composables/useFacetLabels.ts";
import { useScreenHeading } from "@/manuspectrum/pages/AnalysisExplorer/composables/useScreenHeading.ts";
import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";
import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { intervalOf } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/aoristic.ts";
import { materialCounts } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/colour-groups.ts";
import { matchingEvents } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/matching.ts";
import {
    fitAspect,
    fitBoundsOf,
    padBounds,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import {
    FALLBACK_COLOURS,
    readColours,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-colours.ts";
import {
    DEFAULT_EVENT_TYPES,
    shownEventTypes,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-state.ts";
import {
    MINI_HEIGHT,
    MINI_WIDTH,
    MULTIPLES_PER_PAGE,
    byCentury,
    byMaterial,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/multiples.ts";
import {
    featureStates,
    inBrush,
    levelCounts,
    lowLevels,
    placeFeatures,
    summarisePlaces,
    territoryFields,
    withoutApproximate,
    withoutLevels,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/place-symbols.ts";
import {
    THRESHOLD_MAX,
    THRESHOLD_MIN,
    THRESHOLD_STEP,
    gridBounds,
    territories,
    tooCoarse,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/territories.ts";
import { trackedOf } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";
import { webglAvailable } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/webgl.ts";

import type {
    EventType,
    MapEvent,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { Bounds } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import type {
    MapMode,
    MultiplesAxis,
    TerritoryColour,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-state.ts";
import type {
    MapSnapshot,
    MiniMap,
    SnapshotSize,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/multiples.ts";
import type { PanelSubject } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/panel-groups.ts";

interface Hovered {
    id: string;
    x: number;
    y: number;
    /** The tooltip opens to the left of, or above, the pointer past the middle of the frame. */
    flipX: boolean;
    flipY: boolean;
}

type RailGroup = "materials" | "reliability" | "events";

const EUROPE: Bounds = { west: -10, south: 36, east: 20, north: 56 };
const MODES: readonly MapMode[] = ["places", "territories", "multiples"];
const COMPACT_QUERY = "(max-width: 80rem)";
const NARROW_QUERY = "(max-width: 48rem)";
const PHONE_QUERY = "(max-width: 30rem)";
const RADIUS_MIN = 60;
const RADIUS_MAX = 400;
const RADIUS_STEP = 10;
const HEADING_ID = "explorer-map-title";
const CANVAS_SELECTOR = ".maplibregl-canvas";
const PRESSED_MODE_SELECTOR = ".mode-switch button[aria-pressed='true']";

/**
 * The Map & timeline view: the kept events on a MapLibre stage (places,
 * territories of the followed materials, or small multiples), their
 * timeline, the filters of the map in a rail, and the panel of the place,
 * period, document or material opened. The mode, the followed materials,
 * the kernel radius and influence threshold of Territories,
 * the brushed period and the borders live in the store (`mapState`, in the
 * address), with the legend's open state (folded by default, not in the
 * address); the reliability and approximate-date switches, the hovered
 * place, the isolated territory and the opened subject live here. The stage stays laid out,
 * hidden, while the small multiples show, so its snapshot can be taken and
 * the map comes back as it was; a snapshot is asked again only when the
 * bounds change (`boundsKey`), and only the newest answer is kept. A place
 * picked in the list is eased into view. The opened subject's opener gets
 * the focus back on close.
 */
const announce = inject(ANNOUNCE_KEY, null);

const store = useExplorerStore();
const gettext = useGettext();
const { $gettext, $ngettext, interpolate } = gettext;
const { eventTypeLabel, viewTitle } = useVocabulary();
const { activeFilters } = useActiveFilters();
const request = useEvents(() => store.filters);
const compact = useMediaQuery(COMPACT_QUERY);
const narrow = useMediaQuery(NARROW_QUERY);
const phone = useMediaQuery(PHONE_QUERY);
const webgl = webglAvailable();
const root = useTemplateRef<HTMLElement>("root");
const heading = useTemplateRef<HTMLElement>("heading");
const stage = useTemplateRef<InstanceType<typeof MapStage>>("stage");
const rail = useTemplateRef<{ focusFilters: () => void }>("rail");
const timelineBox = useTemplateRef<HTMLElement>("timeline-box");
useScreenHeading(() => heading.value);

const subject = ref<PanelSubject | null>(null);
const hovered = ref<Hovered | null>(null);
const listHovered = ref<string | null>(null);
const page = ref(0);
/** The reliability levels the reader unticked (in the address): their materials leave the map and its exports. */
const hiddenLevels = computed(() => new Set(store.mapState.hiddenLevels));
/** Unticked (in the address), the events dated « circa » leave the map, the lists, the territories, the timeline and the exports. */
const approximateShown = computed({
    get: () => store.mapState.approximate,
    set: (value: boolean) => store.setMapState({ approximate: value }),
});
const background = ref<MapSnapshot | null>(null);
/** The snapshot of an enlarged map of the series, at the dialog's size. */
const largeBackground = ref<MapSnapshot | null>(null);
const mapFailed = ref(false);
const mapColours = shallowRef(FALLBACK_COLOURS);
/** The followed slot whose territory reads alone while its legend row or rail chip is hovered. */
const isolated = ref<number | null>(null);
/** The bounds the stage shows, once it has loaded: the territories' grid covers them. */
const viewport = shallowRef<Bounds | null>(null);
const radiusDraft = ref(store.mapState.radius);
const thresholdDraft = ref(store.mapState.threshold);
const folded = ref(new Set<RailGroup>());
let opener: HTMLElement | null = null;
let snapshotTicket = 0;
let largeTicket = 0;

const response = computed(() => request.data.value);
useEventLabels(() => response.value);
const status = computed(() => request.status.value);
const firstLoad = computed(
    () =>
        response.value === null &&
        (status.value === "loading" || status.value === "idle"),
);
const failed = computed(
    () => status.value === "error" || status.value === "unavailable",
);
const refetching = computed(
    () => status.value === "loading" && response.value !== null,
);
const mode = computed(() => store.mapState.mode);
const low = computed(() =>
    lowLevels(response.value?.certaintyScale ?? { levels: [] }),
);
const places = computed(() => response.value?.places ?? {});
/** The kept events under « Include approximate dates »: every count reads these. */
const dated = computed<MapEvent[]>(() => {
    const all = response.value?.events ?? [];
    return approximateShown.value ? all : withoutApproximate(all);
});
/** Every listed material of the kept events: the rail's list of materials reads these. */
const events = computed<MapEvent[]>(() =>
    withoutLevels(dated.value, hiddenLevels.value),
);
/** The kept events with their matching materials only: every result reads these. */
const shown = computed(() => matchingEvents(events.value));
const brushed = computed(() =>
    shown.value.filter((event) => inBrush(event, store.mapState.brush)),
);
const tracked = computed(() => trackedOf(store.mapState.track));
const summaries = computed(() =>
    summarisePlaces(brushed.value, places.value, tracked.value, low.value),
);
const summaryList = computed(() => [...summaries.value.values()]);
const features = computed(() => placeFeatures(summaries.value));
const states = computed(
    () =>
        new Map(
            summaryList.value.map((summary) => [
                summary.id,
                {
                    ...featureStates(summary, tracked.value, store.trackMode),
                    hover: summary.id === listHovered.value,
                },
            ]),
        ),
);
/** The fitted view of the stage and of the series maps: across the antimeridian when the places sit around it. */
const bounds = computed(() =>
    padBounds(
        fitBoundsOf(summaryList.value.map((summary) => summary.lngLat)) ??
            EUROPE,
        store.mapState.radius,
    ),
);
/** The bounds rounded to a hundredth of a degree: equal bounds ask no new snapshot. */
const boundsKey = computed(() =>
    [
        bounds.value.west,
        bounds.value.south,
        bounds.value.east,
        bounds.value.north,
    ]
        .map((value) => value.toFixed(2))
        .join(","),
);
const territoryReason = computed(() =>
    tracked.value.length === 0
        ? $gettext("Follow at least one material to draw territories.")
        : null,
);
const territoryGrid = computed(() =>
    viewport.value ? gridBounds(viewport.value) : null,
);
/** Zoomed out past what `MAX_CELLS` cells can show at the kernel radius: no zone is drawn. */
const territoryCoarse = computed(
    () =>
        mode.value === "territories" &&
        territoryGrid.value !== null &&
        tooCoarse(store.mapState.radius, territoryGrid.value),
);
/** The attestations of the followed materials, read once per set of kept places, not once per view. */
const territoryInput = computed(() =>
    mode.value === "territories"
        ? territoryFields(summaries.value, tracked.value, low.value)
        : [],
);
const territoryData = computed(() => {
    if (
        mode.value !== "territories" ||
        tracked.value.length === 0 ||
        !territoryGrid.value
    ) {
        return null;
    }
    return territories(
        territoryInput.value,
        store.mapState.radius,
        territoryGrid.value,
        store.mapState.colour,
        store.mapState.threshold,
    );
});
const nothingToDraw = computed(
    () =>
        !territoryCoarse.value &&
        territoryData.value !== null &&
        territoryData.value.features.length === 0,
);
/** The years the kept events span, for the century multiples and the stage title without a brush. */
const eventsRange = computed<[number, number] | null>(() => {
    let from = Infinity;
    let to = -Infinity;
    for (const event of shown.value) {
        const interval = intervalOf(event.date);
        if (!interval) continue;
        from = Math.min(from, interval[0]);
        to = Math.max(to, interval[1]);
    }
    return Number.isFinite(from) ? [from, to] : null;
});
const minis = computed<MiniMap[]>(() => {
    if (mode.value !== "multiples") return [];
    if (store.mapState.multiples === "material") {
        const ticked = store.filters.material;
        return byMaterial(
            brushed.value,
            places.value,
            ticked.length > 0
                ? ticked
                : Object.keys(response.value?.materials ?? {}),
            low.value,
            tracked.value,
        );
    }
    const range = store.mapState.brush ?? eventsRange.value;
    return range
        ? byCentury(
              brushed.value,
              places.value,
              tracked.value,
              low.value,
              range,
          )
        : [];
});
const pages = computed(() =>
    Math.max(1, Math.ceil(minis.value.length / MULTIPLES_PER_PAGE)),
);
const bordersYear = computed(() => {
    const brush = store.mapState.brush;
    return brush ? Math.round((brush[0] + brush[1]) / 2) : null;
});
const bordersShown = computed(
    () => store.mapState.borders && bordersYear.value !== null,
);
const bordersLabel = computed(() =>
    bordersYear.value === null
        ? $gettext("Historical borders")
        : interpolate(
              $gettext("Historical borders (%{year})"),
              { year: bordersYear.value },
              true,
          ),
);
/** The licence credits under the map; OpenHistoricalMap's only while its borders are drawn. */
const credits = computed<{ href: string; text: string }[]>(() => [
    {
        href: "https://www.openstreetmap.org/copyright",
        text: contributorsCredit("OpenStreetMap"),
    },
    { href: "https://www.openmaptiles.org/", text: "© OpenMapTiles" },
    { href: "https://openfreemap.org/", text: "OpenFreeMap" },
    ...(bordersShown.value
        ? [
              {
                  href: "https://www.openhistoricalmap.org/copyright",
                  text: contributorsCredit("OpenHistoricalMap"),
              },
          ]
        : []),
]);
const language = computed(() => gettext.current);
const switches = computed(() => ({
    approximate: store.mapState.approximate,
    hiddenLevels: store.mapState.hiddenLevels,
}));
const exports = computed(() => ({
    csv: exportHref(
        "manuspectrum:explorer-events-csv",
        store.filters,
        language.value,
        switches.value,
    ),
    geojson: exportHref(
        "manuspectrum:explorer-events-geojson",
        store.filters,
        language.value,
        switches.value,
    ),
}));
const unplaced = computed(
    () =>
        brushed.value.filter(
            (event) => !(event.place && places.value[event.place]?.lngLat),
        ).length,
);
const unplacedText = computed(() =>
    interpolate(
        $ngettext(
            "%{n} event without a mapped place",
            "%{n} events without a mapped place",
            unplaced.value,
        ),
        { n: unplaced.value },
    ),
);
const levels = computed(() =>
    [...(response.value?.certaintyScale.levels ?? [])].sort(
        (a, b) => a.rank - b.rank,
    ),
);
const levelCount = computed(() => levelCounts(matchingEvents(dated.value)));
const shownTypes = computed(() => shownEventTypes(store.filters.eventType));
const typeCounts = computed(() => {
    const counts = new Map<EventType, number>();
    for (const event of shown.value) {
        counts.set(event.type, (counts.get(event.type) ?? 0) + 1);
    }
    return counts;
});
const showLabel = computed(() =>
    interpolate(
        $ngettext("See %{n} event", "See %{n} events", brushed.value.length),
        { n: brushed.value.length },
    ),
);
const modeLabels = computed<Record<MapMode, string>>(() => ({
    places: $gettext("Places"),
    territories: $gettext("Territories"),
    multiples: $gettext("Map series"),
}));
const colourOptions = computed<{ id: TerritoryColour; label: string }[]>(() => [
    { id: "each", label: $gettext("Each material") },
    { id: "dominant", label: $gettext("Dominant") },
]);
const axisOptions = computed<{ id: MultiplesAxis; label: string }[]>(() => [
    { id: "material", label: $gettext("Material") },
    { id: "century", label: $gettext("Century") },
]);
const selectedPlace = computed(() =>
    subject.value?.kind === "place" ? subject.value.id : null,
);
/** A period opens on every kept event of its years; any other subject on the brushed ones, as the map shows them. */
const panelEvents = computed(() =>
    subject.value?.kind === "period" ? shown.value : brushed.value,
);
const drawerVisible = computed({
    get: () => narrow.value && subject.value !== null,
    set: (visible: boolean) => {
        if (!visible) closePanel();
    },
});
const followed = computed(() => {
    const counts = materialCounts(brushed.value);
    return tracked.value.map(({ uri, slot }) => ({
        uri,
        slot,
        label: response.value?.materials[uri]?.label ??
            counts.get(uri)?.label ?? { value: uri, lang: "" },
        documents: counts.get(uri)?.documents ?? 0,
    }));
});
const stageTitle = computed(() => {
    const title =
        mode.value === "territories"
            ? store.mapState.colour === "dominant"
                ? $gettext("Dominant material")
                : $gettext("Areas by material")
            : $gettext("Places");
    const range = store.mapState.brush ?? eventsRange.value;
    if (!range) return title;
    return interpolate(
        $gettext("%{title} · %{period}"),
        {
            title,
            period: interpolate(
                $gettext("%{start}–%{end}"),
                { start: range[0], end: range[1] },
                true,
            ),
        },
        true,
    );
});
const territorySentence = computed(() => {
    if (territoryReason.value) return territoryReason.value;
    if (nothingToDraw.value) {
        return $gettext(
            "Nothing to draw: the followed materials are not attested in the kept events.",
        );
    }
    return store.mapState.colour === "dominant"
        ? $gettext(
              "Gaussian kernel estimate from the attesting places, each cell in the colour of the most influential material: see ⓘ for the method.",
          )
        : $gettext(
              "Gaussian kernel estimate from the attesting places, one area per material: see ⓘ for the method.",
          );
});
/** The method of the influence model, one paragraph per step, for the note's ⓘ. */
const methodText = computed(() =>
    [
        $gettext(
            "Attestation: each document and each Component of the kept events that carries a followed material at a place. It weighs 1, or 0.5 when every identification of that material it carries has a lower reliability.",
        ),
        $gettext(
            "Kernel: an attestation of weight w spreads w × exp(−(d/r)²) at distance d, where r is the kernel radius, or the place's own extent if larger; at d = r it still weighs about 37%.",
        ),
        $gettext(
            "Grid: the influences of every place are summed at the centre of each cell of a hexagonal grid laid over the visible map.",
        ),
        $gettext(
            "Threshold t: a cell is drawn when its summed influence reaches t, and a place always colours its own cell. One attestation alone reaches t out to d = r × √(ln(1/t)) when t < 1: 0.83 r at the default 0.5.",
        ),
        $gettext(
            "Dominant: each cell takes the colour of the most influential material, its opacity that material's share of the total; it is hatched when the leader holds less than 55% of the top two.",
        ),
        $gettext(
            "The zones are a model that extrapolates between attested places, not observed data.",
        ),
    ].join("\n\n"),
);
const coarseSentence = $gettext(
    "Zoom in to see the influence zones: at this scale the grid is coarser than the kernel radius.",
);
const legendOpen = computed(() => store.mapState.legend);
/** The influence note folds to its title; the reader's choice lasts for the view. */
const noteOpen = ref(false);
const isolateHint = computed(
    () =>
        store.mapState.colour === "each" &&
        tracked.value.length >= 3 &&
        !nothingToDraw.value &&
        !territoryCoarse.value,
);
const radiusHelp = $gettext(
    "Distance at which a place's weight falls to about 37% (or the place's own extent if larger)",
);
const radiusText = computed(() =>
    interpolate($gettext("%{n} km"), { n: radiusDraft.value }),
);
const thresholdHelp = $gettext(
    "Summed influence a cell must reach to be drawn; one full attestation weighs 1 at its place",
);
const thresholdNumber = computed(() =>
    new Intl.NumberFormat(language.value, {
        maximumFractionDigits: 2,
    }).format(thresholdDraft.value),
);
const thresholdText = computed(() =>
    interpolate($gettext("≥ %{n}"), { n: thresholdNumber.value }),
);
const thresholdValueText = computed(() =>
    interpolate(
        $ngettext(
            "at least %{n} attestation",
            "at least %{n} attestations",
            thresholdDraft.value,
        ),
        { n: thresholdNumber.value },
    ),
);
const tooltip = computed(() => {
    const current = hovered.value;
    const summary = current ? summaries.value.get(current.id) : undefined;
    if (!current || !summary) return null;
    return {
        position: {
            "--tip-x": `${current.x}px`,
            "--tip-y": `${current.y}px`,
        },
        flipX: current.flipX,
        flipY: current.flipY,
        name: summary.name,
        counts: countsText(
            summary.documents.size,
            summary.components.size,
            summary.analyses.size,
        ),
        slots: followed.value
            .filter(({ slot }) => summary.tracked.has(slot))
            .map((entry) => ({
                ...entry,
                pale: summary.tracked.get(entry.slot) === "pale",
            })),
        attributed: summary.dashed,
    };
});

watch(
    () => [mode.value, boundsKey.value, stage.value] as const,
    async ([current]) => {
        if (current !== "multiples" || !stage.value) return;
        const ticket = ++snapshotTicket;
        const shot = await stage.value.snapshot(
            fitAspect(bounds.value, MINI_WIDTH, MINI_HEIGHT),
        );
        if (ticket === snapshotTicket && shot) background.value = shot;
    },
    { immediate: true, flush: "post" },
);
watch(boundsKey, () => {
    snapshotTicket += 1;
    largeTicket += 1;
    background.value = null;
    largeBackground.value = null;
});
watch(mode, (current, previous) => {
    if (previous === "multiples" && current !== "multiples") {
        snapshotTicket += 1;
        largeTicket += 1;
        largeBackground.value = null;
        stage.value?.cancelSnapshots();
        void nextTick(() => stage.value?.resize());
    }
});
watch(
    () => store.filters,
    () => {
        page.value = 0;
    },
);
watch(
    () => store.mapState.radius,
    (radius) => {
        radiusDraft.value = radius;
    },
);
watch(
    () => store.mapState.threshold,
    (threshold) => {
        thresholdDraft.value = threshold;
    },
);

onMounted(() => {
    if (root.value) mapColours.value = readColours(root.value);
});

function countsText(
    documents: number,
    components: number,
    analyses: number,
): string {
    return interpolate($gettext("%{documents} · %{components} · %{analyses}"), {
        documents: interpolate(
            $ngettext("%{n} document", "%{n} documents", documents),
            { n: documents },
        ),
        components: interpolate(
            $ngettext("%{n} Component", "%{n} Components", components),
            { n: components },
        ),
        analyses: interpolate(
            $ngettext("%{n} analysis", "%{n} analyses", analyses),
            { n: analyses },
        ),
    });
}

function setMode(next: MapMode): void {
    if (next === "territories" && territoryReason.value) return;
    if (next === mode.value) return;
    store.setMapState({ mode: next });
    announce?.(
        interpolate($gettext("Map mode: %{mode}."), {
            mode: modeLabels.value[next],
        }),
    );
}

function toggleLegend(): void {
    store.setMapState({ legend: !legendOpen.value });
}

function brushPeriod(range: [number, number]): void {
    store.setMapState({ brush: range });
}

function setColour(colour: TerritoryColour): void {
    store.setMapState({ colour });
}

function setAxis(axis: MultiplesAxis): void {
    page.value = 0;
    store.setMapState({ multiples: axis });
}

function commitRadius(): void {
    store.setMapState({ radius: radiusDraft.value });
}

function onRadiusInput(event: Event): void {
    radiusDraft.value = Number((event.target as HTMLInputElement).value);
}

function commitThreshold(): void {
    store.setMapState({ threshold: thresholdDraft.value });
}

function onThresholdInput(event: Event): void {
    thresholdDraft.value = Number((event.target as HTMLInputElement).value);
}

function setBorders(event: Event): void {
    store.setMapState({
        borders: (event.target as HTMLInputElement).checked,
    });
}

/** Ticks or unticks a type; none left means all three, and all three means no filter. */
function toggleType(type: EventType, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    let next = checked
        ? [...shownTypes.value, type]
        : shownTypes.value.filter((shown) => shown !== type);
    if (next.length === 0) next = [...DEFAULT_EVENT_TYPES];
    const isDefault =
        next.length === DEFAULT_EVENT_TYPES.length &&
        DEFAULT_EVENT_TYPES.every((fallback) => next.includes(fallback));
    store.setFilter("eventType", isDefault ? [] : next);
}

/** « © <name> contributors »: the name of the project stays untranslated. */
function contributorsCredit(name: string): string {
    return interpolate($gettext("© %{name} contributors"), { name }, true);
}

function setLevel(id: string, event: Event): void {
    const next = new Set(hiddenLevels.value);
    if ((event.target as HTMLInputElement).checked) next.delete(id);
    else next.add(id);
    store.setMapState({ hiddenLevels: [...next].sort() });
}

function isFolded(group: RailGroup): boolean {
    return folded.value.has(group);
}

function toggleGroup(group: RailGroup): void {
    const next = new Set(folded.value);
    if (next.has(group)) next.delete(group);
    else next.add(group);
    folded.value = next;
}

function groupBodyId(group: RailGroup): string {
    return `explorer-map-group-${group}`;
}

function openSubject(next: PanelSubject): void {
    const active = document.activeElement;
    opener =
        active instanceof HTMLElement && active !== document.body
            ? active
            : null;
    subject.value = next;
}

/** Closes the panel; the focus goes back to what opened it, else to the map. */
function closePanel(): void {
    subject.value = null;
    const target = opener;
    opener = null;
    void nextTick(() => {
        if (target?.isConnected) {
            target.focus();
            return;
        }
        root.value?.querySelector<HTMLElement>(CANVAS_SELECTOR)?.focus();
    });
}

function onStageHover(
    payload: { id: string; x: number; y: number } | null,
): void {
    if (!payload) {
        hovered.value = null;
        return;
    }
    const frame = (
        stage.value?.$el as HTMLElement | undefined
    )?.getBoundingClientRect();
    hovered.value = {
        ...payload,
        flipX: frame ? payload.x > frame.width / 2 : false,
        flipY: frame ? payload.y > frame.height / 2 : false,
    };
}

function openMini(mini: MiniMap): void {
    if (mini.uri) {
        openSubject({ kind: "material", uri: mini.uri });
    } else if (mini.century !== null) {
        openSubject({
            kind: "period",
            from: mini.century * 100 + 1,
            to: (mini.century + 1) * 100,
        });
    }
}

/** Takes the snapshot of an enlarged map of the series at the dialog's drawing size. */
async function snapshotLarge(size: SnapshotSize): Promise<void> {
    if (!stage.value) return;
    const ticket = ++largeTicket;
    const shot = await stage.value.snapshot(
        fitAspect(bounds.value, size.width, size.height),
        size,
    );
    if (ticket === largeTicket && shot) largeBackground.value = shot;
}

/** The main map in Places with what a map of the series shows: its material added to the ticked ones, or its century as the period. The focus moves to the stage, or to the pressed mode without a map. */
function showSeriesMap(mini: MiniMap): void {
    if (mini.uri) {
        const ticked = store.filters.material;
        if (!ticked.includes(mini.uri)) {
            store.setFilter("material", [...ticked, mini.uri]);
        }
    } else if (mini.century !== null) {
        store.setMapState({
            brush: [mini.century * 100 + 1, (mini.century + 1) * 100],
        });
    }
    setMode("places");
    void nextTick(() => {
        const target =
            root.value?.querySelector<HTMLElement>(CANVAS_SELECTOR) ??
            root.value?.querySelector<HTMLElement>(PRESSED_MODE_SELECTOR);
        target?.focus({ preventScroll: true });
    });
}

/** Opens a place picked in the list, easing the map to it when it is off screen. */
function pickPlace(id: string): void {
    openSubject({ kind: "place", id });
    const summary = summaries.value.get(id);
    if (summary) stage.value?.revealPlace(summary.lngLat);
}

function skipToPlaces(): void {
    if (compact.value) {
        rail.value?.focusFilters();
        return;
    }
    const target =
        root.value?.querySelector<HTMLElement>(".place-list .place") ??
        root.value?.querySelector<HTMLElement>(".place-list .toggle");
    target?.focus();
}

function skipToTimeline(): void {
    timelineBox.value?.focus();
}
</script>

<template>
    <section
        ref="root"
        class="map-view"
        :aria-labelledby="HEADING_ID"
    >
        <h2
            :id="HEADING_ID"
            ref="heading"
            class="visually-hidden"
            tabindex="-1"
        >
            <span>{{ viewTitle("map") }}</span>
        </h2>
        <nav
            class="skip-links"
            :aria-label="$gettext('Skip links')"
        >
            <button
                type="button"
                class="skip"
                @click="skipToPlaces"
            >
                <span>{{ $gettext("Skip to the place list") }}</span>
            </button>
            <button
                type="button"
                class="skip"
                @click="skipToTimeline"
            >
                <span>{{ $gettext("Skip to the timeline") }}</span>
            </button>
        </nav>
        <BusyStatus
            :busy="status === 'loading'"
            :first="response === null"
        />
        <div
            v-if="firstLoad"
            class="workspace skeleton"
            aria-hidden="true"
        >
            <span class="ms-skeleton rail-block"></span>
            <div class="main">
                <span class="ms-skeleton stage-block"></span>
                <span class="ms-skeleton timeline-block"></span>
            </div>
            <span class="ms-skeleton side-block"></span>
        </div>
        <div
            v-else
            class="workspace"
        >
            <RailPanel
                ref="rail"
                class="rail"
                :show-label="showLabel"
            >
                <div class="map-rail">
                    <section class="group">
                        <h3 class="group-title">
                            <button
                                type="button"
                                class="disclosure"
                                :aria-expanded="
                                    isFolded('materials') ? 'false' : 'true'
                                "
                                :aria-controls="groupBodyId('materials')"
                                @click="toggleGroup('materials')"
                            >
                                <span
                                    class="chevron"
                                    aria-hidden="true"
                                    >{{
                                        isFolded("materials") ? "▸" : "▾"
                                    }}</span
                                >
                                <span>{{
                                    $gettext("Identified materials")
                                }}</span>
                            </button>
                        </h3>
                        <div
                            v-show="!isFolded('materials')"
                            :id="groupBodyId('materials')"
                            class="group-body"
                        >
                            <MaterialsControl
                                :events="events"
                                :materials="response?.materials ?? {}"
                                :colours="response?.colours ?? {}"
                                :covering-materials="
                                    response?.coveringMaterials ?? {}
                                "
                                @isolate="isolated = $event"
                            />
                        </div>
                    </section>
                    <section class="group">
                        <h3 class="group-title">
                            <button
                                type="button"
                                class="disclosure"
                                :aria-expanded="
                                    isFolded('reliability') ? 'false' : 'true'
                                "
                                :aria-controls="groupBodyId('reliability')"
                                @click="toggleGroup('reliability')"
                            >
                                <span
                                    class="chevron"
                                    aria-hidden="true"
                                    >{{
                                        isFolded("reliability") ? "▸" : "▾"
                                    }}</span
                                >
                                <span>{{ $gettext("Reliability") }}</span>
                            </button>
                        </h3>
                        <div
                            v-show="!isFolded('reliability')"
                            :id="groupBodyId('reliability')"
                            class="group-body"
                        >
                            <ul class="levels">
                                <li
                                    v-for="level in levels"
                                    :key="level.id"
                                >
                                    <label
                                        class="value"
                                        :class="{
                                            checked: !hiddenLevels.has(
                                                level.id,
                                            ),
                                        }"
                                    >
                                        <input
                                            type="checkbox"
                                            :checked="
                                                !hiddenLevels.has(level.id)
                                            "
                                            @change="setLevel(level.id, $event)"
                                        />
                                        <span
                                            class="label"
                                            :lang="
                                                level.label.lang || undefined
                                            "
                                            :title="level.label.value"
                                            >{{ level.label.value }}</span
                                        >
                                        <span class="count">{{
                                            levelCount.get(level.id) ?? 0
                                        }}</span>
                                    </label>
                                </li>
                            </ul>
                            <p class="hint">
                                <span>{{
                                    $gettext(
                                        "Lower reliability levels are drawn hollow on the map.",
                                    )
                                }}</span>
                            </p>
                        </div>
                    </section>
                    <section class="group">
                        <h3 class="group-title">
                            <button
                                type="button"
                                class="disclosure"
                                :aria-expanded="
                                    isFolded('events') ? 'false' : 'true'
                                "
                                :aria-controls="groupBodyId('events')"
                                @click="toggleGroup('events')"
                            >
                                <span
                                    class="chevron"
                                    aria-hidden="true"
                                    >{{ isFolded("events") ? "▸" : "▾" }}</span
                                >
                                <span>{{ $gettext("Events") }}</span>
                            </button>
                        </h3>
                        <div
                            v-show="!isFolded('events')"
                            :id="groupBodyId('events')"
                            class="group-body"
                        >
                            <ul class="event-types">
                                <li
                                    v-for="type in DEFAULT_EVENT_TYPES"
                                    :key="type"
                                >
                                    <label
                                        class="value"
                                        :class="{
                                            checked: shownTypes.includes(type),
                                        }"
                                    >
                                        <input
                                            type="checkbox"
                                            :checked="shownTypes.includes(type)"
                                            @change="toggleType(type, $event)"
                                        />
                                        <span class="label">{{
                                            eventTypeLabel(type)
                                        }}</span>
                                        <span
                                            v-if="shownTypes.includes(type)"
                                            class="count"
                                            >{{
                                                typeCounts.get(type) ?? 0
                                            }}</span
                                        >
                                    </label>
                                </li>
                            </ul>
                        </div>
                    </section>
                    <PlaceList
                        :summaries="summaryList"
                        :unplaced="unplaced"
                        :selected="selectedPlace"
                        :open="!compact"
                        :places="places"
                        @select="pickPlace"
                        @hover="listHovered = $event"
                    />
                </div>
            </RailPanel>
            <div class="main">
                <section
                    class="stage"
                    :aria-label="$gettext('Map')"
                    :aria-busy="refetching ? 'true' : 'false'"
                >
                    <div class="stage-head">
                        <span
                            class="segmented mode-switch"
                            role="group"
                            :aria-label="$gettext('Map mode')"
                        >
                            <template
                                v-for="option in MODES"
                                :key="option"
                            >
                                <HelpTip
                                    v-if="
                                        option === 'territories' &&
                                        territoryReason
                                    "
                                    :text="territoryReason"
                                    placement="below"
                                >
                                    <template #default="{ describedby }">
                                        <button
                                            type="button"
                                            aria-disabled="true"
                                            :aria-pressed="
                                                mode === option
                                                    ? 'true'
                                                    : 'false'
                                            "
                                            :aria-describedby="describedby"
                                            @click="setMode(option)"
                                        >
                                            <span>{{
                                                modeLabels[option]
                                            }}</span>
                                        </button>
                                    </template>
                                </HelpTip>
                                <button
                                    v-else
                                    type="button"
                                    :aria-pressed="
                                        mode === option ? 'true' : 'false'
                                    "
                                    @click="setMode(option)"
                                >
                                    <span>{{ modeLabels[option] }}</span>
                                </button>
                            </template>
                        </span>
                        <span
                            v-if="mode === 'territories'"
                            class="options"
                        >
                            <span
                                class="kicker"
                                aria-hidden="true"
                                >{{ $gettext("Colour") }}</span
                            >
                            <span
                                class="segments"
                                role="group"
                                :aria-label="$gettext('Colour')"
                            >
                                <button
                                    v-for="option in colourOptions"
                                    :key="option.id"
                                    type="button"
                                    :aria-pressed="
                                        store.mapState.colour === option.id
                                            ? 'true'
                                            : 'false'
                                    "
                                    @click="setColour(option.id)"
                                >
                                    <span>{{ option.label }}</span>
                                </button>
                            </span>
                        </span>
                        <span
                            v-else-if="mode === 'multiples'"
                            class="options"
                        >
                            <span
                                class="kicker"
                                aria-hidden="true"
                                >{{ $gettext("One map per") }}</span
                            >
                            <span
                                class="segments"
                                role="group"
                                :aria-label="$gettext('One map per')"
                            >
                                <button
                                    v-for="option in axisOptions"
                                    :key="option.id"
                                    type="button"
                                    :aria-pressed="
                                        store.mapState.multiples === option.id
                                            ? 'true'
                                            : 'false'
                                    "
                                    @click="setAxis(option.id)"
                                >
                                    <span>{{ option.label }}</span>
                                </button>
                            </span>
                        </span>
                        <span class="tools">
                            <label class="borders">
                                <input
                                    type="checkbox"
                                    :checked="store.mapState.borders"
                                    @change="setBorders"
                                />
                                <span>{{ bordersLabel }}</span>
                            </label>
                            <a
                                class="export"
                                data-format="csv"
                                :href="exports.csv"
                                :aria-label="
                                    $gettext('Download the kept events (CSV)')
                                "
                                download=""
                            >
                                <svg
                                    :viewBox="ICON_VIEW_BOX"
                                    aria-hidden="true"
                                    focusable="false"
                                >
                                    <path
                                        v-for="(path, index) in ICONS.download"
                                        :key="index"
                                        :d="path"
                                    />
                                </svg>
                                <span>{{ $gettext("CSV") }}</span>
                            </a>
                            <a
                                class="export"
                                data-format="geojson"
                                :href="exports.geojson"
                                :aria-label="
                                    $gettext(
                                        'Download the kept events (GeoJSON)',
                                    )
                                "
                                download=""
                            >
                                <svg
                                    :viewBox="ICON_VIEW_BOX"
                                    aria-hidden="true"
                                    focusable="false"
                                >
                                    <path
                                        v-for="(path, index) in ICONS.download"
                                        :key="index"
                                        :d="path"
                                    />
                                </svg>
                                <span>{{ $gettext("GeoJSON") }}</span>
                            </a>
                        </span>
                        <button
                            v-if="unplaced > 0"
                            type="button"
                            class="unplaced"
                            @click="openSubject({ kind: 'unplaced' })"
                        >
                            <span>{{ unplacedText }}</span>
                        </button>
                        <p
                            v-if="
                                store.mapState.borders && bordersYear === null
                            "
                            class="borders-hint"
                        >
                            <span>{{
                                $gettext(
                                    "Narrow the period on the timeline to see its borders.",
                                )
                            }}</span>
                        </p>
                    </div>
                    <UnavailableState
                        v-if="failed"
                        status="error"
                        :hide-home="true"
                        @retry="request.retry"
                    />
                    <div
                        v-else
                        class="frame"
                        :class="{ multiples: mode === 'multiples' }"
                    >
                        <MapStage
                            v-if="webgl && !mapFailed"
                            ref="stage"
                            :class="{ parked: mode === 'multiples' }"
                            :places="features"
                            :states="states"
                            :territories="territoryData"
                            :colours="mapColours"
                            :borders="bordersShown"
                            :borders-year="bordersYear"
                            :fit="bounds"
                            :selected="selectedPlace"
                            :isolate="mode === 'territories' ? isolated : null"
                            @select="openSubject({ kind: 'place', id: $event })"
                            @hover="onStageHover"
                            @failed="mapFailed = true"
                            @view="viewport = $event"
                        >
                            <div
                                class="legend"
                                :class="{ open: legendOpen }"
                            >
                                <button
                                    type="button"
                                    class="toggle"
                                    aria-controls="explorer-map-legend"
                                    :aria-expanded="
                                        legendOpen ? 'true' : 'false'
                                    "
                                    @click="toggleLegend"
                                >
                                    <span>{{ stageTitle }}</span>
                                    <span
                                        v-if="!legendOpen"
                                        class="dots"
                                    >
                                        <FocusSlotDot
                                            v-for="entry in followed"
                                            :key="entry.slot"
                                            :number="entry.slot"
                                            size="small"
                                        />
                                    </span>
                                    <span
                                        class="chevron"
                                        aria-hidden="true"
                                        >{{ legendOpen ? "▾" : "▸" }}</span
                                    >
                                </button>
                                <div
                                    v-show="legendOpen"
                                    id="explorer-map-legend"
                                    class="entries"
                                >
                                    <ul
                                        v-if="followed.length > 0"
                                        class="followed"
                                    >
                                        <li
                                            v-for="entry in followed"
                                            :key="entry.slot"
                                            @mouseenter="isolated = entry.slot"
                                            @mouseleave="isolated = null"
                                        >
                                            <FocusSlotDot
                                                :number="entry.slot"
                                                size="medium"
                                            />
                                            <span
                                                class="name"
                                                :lang="
                                                    entry.label.lang ||
                                                    undefined
                                                "
                                                >{{ entry.label.value }}</span
                                            >
                                            <span class="count">{{
                                                entry.documents
                                            }}</span>
                                        </li>
                                    </ul>
                                    <ul class="key">
                                        <li>
                                            <span
                                                class="symbol ring"
                                                aria-hidden="true"
                                            ></span>
                                            <span>{{
                                                $gettext(
                                                    "documents analysed here",
                                                )
                                            }}</span>
                                        </li>
                                        <li>
                                            <span
                                                class="symbol ring dashed"
                                                aria-hidden="true"
                                            ></span>
                                            <span>{{
                                                $gettext(
                                                    "attributed place: region or parent place",
                                                )
                                            }}</span>
                                        </li>
                                        <li>
                                            <span
                                                class="symbol pip"
                                                aria-hidden="true"
                                                >1</span
                                            >
                                            <span>{{
                                                $gettext("attested")
                                            }}</span>
                                        </li>
                                        <li>
                                            <span
                                                class="symbol pip hollow"
                                                aria-hidden="true"
                                                >1</span
                                            >
                                            <span>{{
                                                $gettext("lower reliability")
                                            }}</span>
                                        </li>
                                        <template v-if="mode === 'territories'">
                                            <li>
                                                <span
                                                    class="symbol hex"
                                                    aria-hidden="true"
                                                ></span>
                                                <span>{{
                                                    $gettext(
                                                        "area of a followed material",
                                                    )
                                                }}</span>
                                            </li>
                                            <li
                                                v-if="
                                                    store.mapState.colour ===
                                                    'dominant'
                                                "
                                            >
                                                <span
                                                    class="symbol hex hatched"
                                                    aria-hidden="true"
                                                ></span>
                                                <span>{{
                                                    $gettext("nearly tied")
                                                }}</span>
                                            </li>
                                        </template>
                                    </ul>
                                </div>
                            </div>
                            <div
                                v-if="mode === 'territories' && !narrow"
                                class="territory-note"
                                role="note"
                            >
                                <p class="title">
                                    <button
                                        type="button"
                                        class="note-toggle"
                                        aria-controls="explorer-map-note-body"
                                        :aria-expanded="
                                            noteOpen ? 'true' : 'false'
                                        "
                                        @click="noteOpen = !noteOpen"
                                    >
                                        <span
                                            class="chevron"
                                            aria-hidden="true"
                                            >{{ noteOpen ? "▾" : "▸" }}</span
                                        >
                                        <span>{{
                                            $gettext(
                                                "Influence zones: a spatial model, not observed data",
                                            )
                                        }}</span>
                                    </button>
                                    <span class="method">
                                        <IconButton
                                            icon="info-circle"
                                            info
                                            :label="
                                                $gettext(
                                                    'About the influence model',
                                                )
                                            "
                                            :description="methodText"
                                            tip-placement="above"
                                            tip-align="start"
                                        />
                                    </span>
                                </p>
                                <p
                                    v-if="territoryCoarse"
                                    class="sentence coarse"
                                >
                                    <span>{{ coarseSentence }}</span>
                                </p>
                                <div
                                    v-show="noteOpen"
                                    id="explorer-map-note-body"
                                    class="note-body"
                                >
                                    <p class="sentence">
                                        <span>{{ territorySentence }}</span>
                                    </p>
                                    <p class="sentence caveat">
                                        <span>{{
                                            $gettext(
                                                "Lower-reliability attestations count half. The zones extrapolate between attested places; they do not attest a use outside them.",
                                            )
                                        }}</span>
                                    </p>
                                    <p
                                        v-if="isolateHint"
                                        class="sentence isolate-hint"
                                    >
                                        <span>{{
                                            $gettext(
                                                "Hover a material in the legend to see its zone alone.",
                                            )
                                        }}</span>
                                    </p>
                                    <p class="radius">
                                        <label for="explorer-map-radius">{{
                                            $gettext("Kernel radius")
                                        }}</label>
                                        <input
                                            id="explorer-map-radius"
                                            :title="radiusHelp"
                                            type="range"
                                            :min="RADIUS_MIN"
                                            :max="RADIUS_MAX"
                                            :step="RADIUS_STEP"
                                            :value="radiusDraft"
                                            :aria-valuetext="radiusText"
                                            @input="onRadiusInput"
                                            @change="commitRadius"
                                        />
                                        <output for="explorer-map-radius">{{
                                            radiusText
                                        }}</output>
                                    </p>
                                    <p class="radius">
                                        <label for="explorer-map-threshold">{{
                                            $gettext("Influence threshold")
                                        }}</label>
                                        <input
                                            id="explorer-map-threshold"
                                            :title="thresholdHelp"
                                            type="range"
                                            :min="THRESHOLD_MIN"
                                            :max="THRESHOLD_MAX"
                                            :step="THRESHOLD_STEP"
                                            :value="thresholdDraft"
                                            :aria-valuetext="thresholdValueText"
                                            @input="onThresholdInput"
                                            @change="commitThreshold"
                                        />
                                        <output for="explorer-map-threshold">{{
                                            thresholdText
                                        }}</output>
                                    </p>
                                </div>
                            </div>
                            <div
                                v-if="tooltip && mode !== 'multiples'"
                                class="tooltip"
                                :class="{
                                    'flip-x': tooltip.flipX,
                                    'flip-y': tooltip.flipY,
                                }"
                                :style="tooltip.position"
                                aria-hidden="true"
                            >
                                <strong
                                    class="name"
                                    :lang="tooltip.name.lang || undefined"
                                    >{{ tooltip.name.value }}</strong
                                >
                                <em>{{ tooltip.counts }}</em>
                                <ul
                                    v-if="tooltip.slots.length > 0"
                                    class="rows"
                                >
                                    <li
                                        v-for="entry in tooltip.slots"
                                        :key="entry.slot"
                                    >
                                        <FocusSlotDot
                                            :number="entry.slot"
                                            size="small"
                                        />
                                        <span class="label">{{
                                            entry.label.value
                                        }}</span>
                                        <em v-if="entry.pale">{{
                                            $gettext("use with caution")
                                        }}</em>
                                    </li>
                                </ul>
                                <span
                                    v-if="tooltip.attributed"
                                    class="attributed"
                                    >{{ $gettext("Attributed place") }}</span
                                >
                            </div>
                        </MapStage>
                        <div
                            v-else
                            class="map-unavailable-frame"
                        >
                            <p
                                class="map-unavailable"
                                role="status"
                            >
                                <span>{{
                                    $gettext(
                                        "Map unavailable in this browser: the place list and the timeline still work.",
                                    )
                                }}</span>
                            </p>
                        </div>
                        <SmallMultiples
                            v-if="mode === 'multiples'"
                            :maps="minis"
                            :bounds="bounds"
                            :background="background"
                            :page="page"
                            :pages="pages"
                            :axis="store.mapState.multiples"
                            :tracked="tracked"
                            :large-background="largeBackground"
                            @open="openMini"
                            @page="page = $event"
                            @enlarge-snapshot="snapshotLarge"
                            @show="showSeriesMap"
                        />
                        <div
                            v-if="response && response.events.length === 0"
                            class="no-events"
                        >
                            <p>
                                <span>{{
                                    $gettext("No event matches these filters.")
                                }}</span>
                            </p>
                            <button
                                v-for="filter in activeFilters"
                                :key="filter.id"
                                type="button"
                                class="remove-filter"
                                @click="filter.clear"
                            >
                                <span>{{
                                    interpolate(
                                        $gettext("Remove: %{label}"),
                                        { label: filter.label },
                                        true,
                                    )
                                }}</span>
                            </button>
                        </div>
                    </div>
                    <p
                        v-if="!failed && webgl && !mapFailed"
                        class="credits"
                    >
                        <template
                            v-for="(credit, index) in credits"
                            :key="credit.href"
                        >
                            <span
                                v-if="index > 0"
                                aria-hidden="true"
                                >{{ " · " }}</span
                            >
                            <a
                                rel="noopener"
                                target="_blank"
                                :href="credit.href"
                                ><span>{{ credit.text }}</span
                                ><span class="visually-hidden">{{
                                    $gettext("(new tab)")
                                }}</span></a
                            >
                        </template>
                    </p>
                    <div
                        v-if="mode === 'territories' && narrow && !failed"
                        class="territory-note static"
                        role="note"
                    >
                        <p class="title">
                            <span>{{
                                $gettext(
                                    "Influence zones: a spatial model, not observed data",
                                )
                            }}</span>
                            <span class="method">
                                <IconButton
                                    icon="info-circle"
                                    info
                                    :label="
                                        $gettext('About the influence model')
                                    "
                                    :description="methodText"
                                    tip-placement="above"
                                    tip-align="start"
                                />
                            </span>
                        </p>
                        <p
                            v-if="territoryCoarse"
                            class="sentence coarse"
                        >
                            <span>{{ coarseSentence }}</span>
                        </p>
                        <p class="sentence">
                            <span>{{ territorySentence }}</span>
                        </p>
                        <p class="sentence caveat">
                            <span>{{
                                $gettext(
                                    "Lower-reliability attestations count half. The zones extrapolate between attested places; they do not attest a use outside them.",
                                )
                            }}</span>
                        </p>
                        <p
                            v-if="isolateHint"
                            class="sentence isolate-hint"
                        >
                            <span>{{
                                $gettext(
                                    "Hover a material in the legend to see its zone alone.",
                                )
                            }}</span>
                        </p>
                        <p class="radius">
                            <label for="explorer-map-radius-narrow">{{
                                $gettext("Kernel radius")
                            }}</label>
                            <input
                                id="explorer-map-radius-narrow"
                                :title="radiusHelp"
                                type="range"
                                :min="RADIUS_MIN"
                                :max="RADIUS_MAX"
                                :step="RADIUS_STEP"
                                :value="radiusDraft"
                                :aria-valuetext="radiusText"
                                @input="onRadiusInput"
                                @change="commitRadius"
                            />
                            <output for="explorer-map-radius-narrow">{{
                                radiusText
                            }}</output>
                        </p>
                        <p class="radius">
                            <label for="explorer-map-threshold-narrow">{{
                                $gettext("Influence threshold")
                            }}</label>
                            <input
                                id="explorer-map-threshold-narrow"
                                :title="thresholdHelp"
                                type="range"
                                :min="THRESHOLD_MIN"
                                :max="THRESHOLD_MAX"
                                :step="THRESHOLD_STEP"
                                :value="thresholdDraft"
                                :aria-valuetext="thresholdValueText"
                                @input="onThresholdInput"
                                @change="commitThreshold"
                            />
                            <output for="explorer-map-threshold-narrow">{{
                                thresholdText
                            }}</output>
                        </p>
                    </div>
                </section>
                <section
                    ref="timeline-box"
                    class="timeline-box"
                    tabindex="-1"
                    :aria-label="$gettext('Timeline')"
                    :aria-busy="refetching ? 'true' : 'false'"
                >
                    <MapTimeline
                        v-model:approximate="approximateShown"
                        :events="shown"
                        :tracked="tracked"
                        :brush="store.mapState.brush"
                        @brush="store.setMapState({ brush: $event })"
                        @open-period="
                            openSubject({
                                kind: 'period',
                                from: $event.from,
                                to: $event.to,
                            })
                        "
                        @open-document="
                            openSubject({ kind: 'document', id: $event })
                        "
                    />
                </section>
            </div>
            <aside
                v-if="!narrow"
                class="side"
                :aria-label="$gettext('Details')"
            >
                <MapPanel
                    v-if="subject && response"
                    :subject="subject"
                    :events="panelEvents"
                    :places="places"
                    :analysis-names="response.analysisNames"
                    :analysis-techniques="response.analysisTechniques"
                    :tracked="tracked"
                    :low="low"
                    :materials="response.materials"
                    :certainty="response.certaintyScale"
                    @close="closePanel"
                    @brush="brushPeriod"
                />
                <p
                    v-else
                    class="hint"
                >
                    <span>{{
                        $gettext(
                            "Select a place on the map, a period on the timeline or a document to see its analyses.",
                        )
                    }}</span>
                </p>
            </aside>
        </div>
        <Drawer
            v-model:visible="drawerVisible"
            class="explorer-card-drawer"
            :position="phone ? 'bottom' : 'right'"
            :header="$gettext('Details')"
            :pt="{
                root: { role: 'dialog', 'aria-label': $gettext('Details') },
            }"
        >
            <MapPanel
                v-if="subject && response"
                :subject="subject"
                :events="panelEvents"
                :places="places"
                :analysis-names="response.analysisNames"
                :analysis-techniques="response.analysisTechniques"
                :tracked="tracked"
                :low="low"
                :materials="response.materials"
                :certainty="response.certaintyScale"
                @close="closePanel"
                @brush="brushPeriod"
            />
        </Drawer>
    </section>
</template>

<style scoped>
.map-view {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.75rem;
    padding-block: 0.5rem 2rem;
}

.map-view .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

.map-view .skip-links {
    position: absolute;
    display: flex;
    gap: 0.5rem;
}

.map-view .skip {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

.map-view .skip:focus {
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

/* CorpusDocument .workspace */
.map-view .workspace {
    display: grid;
    grid-template-columns:
        var(--explorer-rail-track-staged, var(--explorer-rail))
        minmax(0, 1fr) var(--explorer-side);
    grid-template-areas: "rail main side";
    gap: 1rem;
    align-items: start;
}

.map-view .rail {
    grid-area: rail;
}

.map-view .main {
    grid-area: main;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.75rem;
    min-inline-size: 0;
}

.map-view .skeleton .rail-block,
.map-view .skeleton .side-block {
    block-size: 24rem;
}

.map-view .skeleton .rail-block {
    grid-area: rail;
}

.map-view .skeleton .side-block {
    grid-area: side;
}

.map-view .skeleton .stage-block {
    block-size: 36rem;
}

.map-view .skeleton .timeline-block {
    block-size: 9rem;
}

.map-view .stage,
.map-view .timeline-box,
.map-view .side {
    min-inline-size: 0;
    border: 0.0625rem solid var(--border);
    border-radius: var(--explorer-radius);
    background: var(--surface);
}

.map-view .stage {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto;
    gap: 0.5rem;
    padding: 0.5rem;
}

.map-view .timeline-box {
    display: grid;
    gap: 0.75rem;
    padding: 0.75rem 1rem;
    scroll-margin-block-start: var(--explorer-top);
}

.map-view .side {
    grid-area: side;
    position: sticky;
    inset-block-start: var(--explorer-top);
    display: grid;
    align-content: start;
    gap: 1.25rem;
    max-block-size: calc(100dvh - var(--explorer-top) - 1rem);
    padding: 1rem;
    overflow-y: auto;
    overscroll-behavior: contain;
}

.map-view .side .hint {
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

/* The rail groups: FacetRail .group */
.map-rail {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 1rem;
}

.map-rail .group {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.5rem;
}

.map-rail > * + * {
    padding-block-start: 0.75rem;
    border-block-start: 0.0625rem solid var(--border);
}

.map-rail > .group {
    padding-block-start: 0;
}

/*
 * A stuck title covers the rail's top padding (RailPanel .rail-panel,
 * 1rem) with its own: a sticky box stops at the scroll container's padding
 * edge, and the rows scrolled past would show through that strip.
 */
.map-rail .group-title {
    --rail-inset: 1rem;

    position: sticky;
    inset-block-start: calc(-1 * var(--rail-inset));
    z-index: 3;
    padding-block-start: var(--rail-inset);
    background: var(--surface);
}

.map-rail .group:first-child > .group-title {
    margin-block-start: calc(-1 * var(--rail-inset));
}

.map-rail .disclosure {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-block-size: 2rem;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--ink);
    font: inherit;
    font-size: 0.75rem;
    font-weight: 600;
    font-variant: all-small-caps;
    letter-spacing: 0.08em;
    cursor: pointer;
}

.map-rail .disclosure .chevron {
    color: var(--ink-muted);
}

.map-rail .group-body {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.25rem;
    list-style: none;
}

/* FacetValues .values.fixed .value */
.map-rail .value {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target);
    min-inline-size: 0;
    padding-inline: 0.5rem;
    border: 0.0625rem solid transparent;
    border-radius: 0.375rem;
    font-size: 0.8125rem;
    cursor: pointer;
}

.map-rail .value.checked {
    border-color: var(--border-hover);
    background: var(--surface-soft, var(--surface));
    font-weight: 600;
}

.map-rail .value input {
    flex: none;
    accent-color: var(--blue-text);
}

.map-rail .value .label {
    flex: 1 1 auto;
    min-inline-size: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.map-rail .levels,
.map-rail .event-types {
    display: grid;
    gap: 0.25rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.map-rail .value .count {
    flex: none;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-weight: 400;
    font-variant-numeric: tabular-nums;
}

.map-rail .hint {
    color: var(--ink-dim);
    font-size: 0.75rem;
}

/* Toolbar: CorpusDocument .stage-head */
.map-view .stage-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1rem;
}

/* XyWorkshop .segmented (gold) */
.map-view .segmented {
    display: inline-flex;
    padding: 0.1875rem;
    border-radius: 999rem;
    background: var(--bg-alt);
    box-shadow: inset 0 0 0 0.0625rem var(--border);
}

.map-view .segmented button {
    min-block-size: 1.75rem;
    padding-inline: 0.75rem;
    border: none;
    border-radius: 999rem;
    background: none;
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.78125rem;
    white-space: nowrap;
    cursor: pointer;
    transition:
        background-color var(--dur-fast, 160ms),
        color var(--dur-fast, 160ms);
}

.map-view .segmented button:hover {
    color: var(--ink);
}

.map-view .segmented button[aria-pressed="true"] {
    background: var(--surface);
    box-shadow:
        0 0.0625rem 0.125rem rgb(26 26 46 / 0.08),
        inset 0 0 0 0.0625rem var(--seg-on-rule);
    color: var(--seg-on-ink);
    font-weight: 600;
}

.map-view .segmented button[aria-disabled="true"] {
    color: var(--ink-dim);
    cursor: default;
}

.map-view .options {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
}

/* FacetRail .title kicker */
.map-view .options .kicker {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

/* SelectionIndicator .segments (ink) */
.map-view .segments {
    display: inline-flex;
    padding: 0.125rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
}

.map-view .segments button {
    min-block-size: 1.75rem;
    padding-inline: 0.75rem;
    border: 0;
    border-radius: 999rem;
    background: none;
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.8125rem;
    white-space: nowrap;
    cursor: pointer;
}

.map-view .segments button[aria-pressed="true"] {
    background: var(--ink);
    color: var(--surface);
    font-weight: 600;
}

.map-view .tools {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin-inline-start: auto;
}

.map-view .borders {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-block-size: var(--explorer-target);
    font-size: 0.8125rem;
    cursor: pointer;
}

.map-view .borders input {
    accent-color: var(--blue-text);
}

.map-view .export {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-block-size: var(--explorer-target);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font-size: 0.8125rem;
    text-decoration: none;
}

.map-view .export:hover {
    border-color: var(--ink-muted);
}

.map-view .export svg {
    inline-size: 0.875rem;
    block-size: 0.875rem;
    fill: currentcolor;
}

.map-view .borders-hint {
    flex-basis: auto;
    margin-inline-start: auto;
    color: var(--ink-muted);
    font-size: 0.75rem;
    text-align: end;
}

.map-view .unplaced {
    min-block-size: var(--explorer-target);
    padding: 0;
    border: none;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
}

.map-view .unplaced:hover {
    text-decoration: underline;
}

.map-view .frame {
    position: relative;
    display: grid;
    min-inline-size: 0;
}

.map-view .frame.multiples {
    overflow: hidden;
}

.map-view .frame .parked {
    position: absolute;
    inset-block-start: 0;
    inset-inline-start: 0;
    visibility: hidden;
    pointer-events: none;
}

.map-view .map-unavailable-frame {
    display: grid;
    place-items: center;
    block-size: 12rem;
    padding: 1rem;
    border-radius: var(--explorer-radius);
    background: var(--stage-soft);
}

/* FolioMap .no-image */
.map-view .map-unavailable,
.map-view .no-events {
    padding: 0.5rem 0.75rem;
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
}

.map-view .no-events {
    position: absolute;
    inset-block-start: 1rem;
    inset-inline: 1rem 3.75rem;
    z-index: 3;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1rem;
}

/* CorpusResults .empty button */
.map-view .no-events .remove-filter {
    min-block-size: var(--explorer-target);
    padding-inline: 0.875rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

/* FolioLegend */
.map-view .legend {
    position: absolute;
    inset-block-start: 0.75rem;
    inset-inline-start: 0.75rem;
    z-index: 2;
    display: grid;
    justify-items: start;
    gap: 0.375rem;
    max-inline-size: min(22rem, 100% - 4rem);
    padding: 0.375rem 0.5rem;
    border-radius: 0.5rem;
    background: color-mix(in srgb, var(--stage) 88%, transparent);
    color: var(--surface);
    font-size: 0.75rem;
}

.map-view .legend.open {
    max-block-size: calc(100% - 1.5rem);
    overflow-y: auto;
    overscroll-behavior: contain;
}

.map-view .legend .toggle {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.375rem;
    min-block-size: 1.5rem;
    padding: 0 0.25rem;
    border: none;
    background: transparent;
    color: inherit;
    font: inherit;
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    letter-spacing: 0.08em;
    text-align: start;
    text-transform: uppercase;
    cursor: pointer;
}

.map-view .legend .dots {
    display: inline-flex;
    gap: 0.25rem;
}

.map-view .legend .dots :deep(.focus-slot-dot),
.map-view .tooltip :deep(.focus-slot-dot) {
    box-shadow: 0 0 0 0.125rem var(--surface);
}

.map-view .legend .entries {
    display: grid;
    gap: 0.5rem;
}

.map-view .legend ul {
    display: grid;
    gap: 0.25rem;
    padding: 0;
    list-style: none;
}

.map-view .legend .followed li {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: 0.5rem;
}

.map-view .legend .followed .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.map-view .legend .count {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    opacity: 0.8;
}

.map-view .legend .key li {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.map-view .legend .symbol {
    display: inline-grid;
    flex: none;
    place-items: center;
    inline-size: 0.875rem;
    block-size: 0.875rem;
    border-radius: 50%;
}

.map-view .legend .symbol.ring {
    border: 0.0625rem solid var(--surface);
    background: color-mix(in srgb, var(--surface) 22%, transparent);
}

.map-view .legend .symbol.ring.dashed {
    border-style: dashed;
}

.map-view .legend .symbol.pip {
    background: var(--focus-1);
    box-shadow: 0 0 0 0.09375rem var(--surface);
    color: var(--focus-on);
    font-family: var(--font-mono);
    font-size: 0.5625rem;
    font-weight: 700;
}

.map-view .legend .symbol.pip.hollow {
    border: 0.09375rem solid var(--focus-1);
    background: var(--surface);
    box-shadow: none;
    color: var(--focus-1);
}

.map-view .legend .symbol.hex {
    border-radius: 0;
    clip-path: polygon(50% 0, 100% 25%, 100% 75%, 50% 100%, 0 75%, 0 25%);
    background: color-mix(in srgb, var(--focus-1) 70%, var(--surface));
}

.map-view .legend .symbol.hex.hatched {
    background: repeating-linear-gradient(
        45deg,
        color-mix(in srgb, var(--focus-1) 70%, var(--surface)) 0 0.125rem,
        var(--bg) 0.125rem 0.1875rem
    );
}

/* The stage note: Territories only, permanent */
.map-view .territory-note {
    position: absolute;
    inset-block-end: 0.75rem;
    inset-inline-start: 0.75rem;
    z-index: 2;
    inset-inline-end: 3rem;
    display: grid;
    gap: 0.375rem;
    inline-size: fit-content;
    max-inline-size: 27.5rem;
    padding: 0.375rem 0.75rem;
    border-radius: 0.625rem;
    background: color-mix(in srgb, var(--stage) 92%, transparent);
    color: var(--surface);
    font-size: 0.8125rem;
}

.map-view .territory-note.static {
    padding: 0.75rem 0.875rem;
    position: static;
    inline-size: auto;
    max-inline-size: none;
}

.map-view .territory-note .title {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    font-weight: 600;
}

.map-view .territory-note .method {
    --explorer-target: 1.5rem;
}

.map-view .territory-note .method :deep(.icon-button-control) {
    color: color-mix(in srgb, var(--surface) 80%, transparent);
}

.map-view .territory-note .method :deep(.icon-button-control:hover) {
    background: color-mix(in srgb, var(--surface) 15%, transparent);
    color: var(--surface);
}

.map-view .territory-note .method :deep(.icon-button-control:focus-visible) {
    outline-color: var(--surface);
}

/* The method reads as paragraphs, wider than a one-line tooltip */
.map-view .territory-note .method :deep(.bubble) {
    max-inline-size: min(26rem, calc(100vw - 1rem));
}

.map-view .territory-note .method :deep(.detail) {
    font-weight: 400;
    white-space: pre-line;
}

.map-view .territory-note .note-toggle {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-block-size: 1.5rem;
    padding: 0;
    border: none;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.map-view .territory-note .note-toggle:focus-visible {
    outline: 0.125rem solid var(--surface);
    outline-offset: 0.125rem;
}

.map-view .territory-note .note-body {
    display: grid;
    gap: 0.375rem;
}

.map-view .territory-note .sentence {
    color: color-mix(in srgb, var(--surface) 80%, transparent);
}

.map-view .territory-note .sentence.coarse {
    color: var(--surface);
}

.map-view .territory-note .radius {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.map-view .territory-note output {
    flex: none;
    min-inline-size: 3.5rem;
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-variant-numeric: tabular-nums;
    text-align: end;
}

/* RangeSlider, recoloured for the stage */
.map-view .territory-note input[type="range"] {
    flex: 1 1 auto;
    min-inline-size: 0;
    block-size: 1.5rem;
    background: transparent;
    accent-color: var(--surface);
    cursor: pointer;
    appearance: none;
}

.map-view .territory-note input[type="range"]::-webkit-slider-runnable-track {
    block-size: 0.25rem;
    border-radius: 0.125rem;
    background: color-mix(in srgb, var(--surface) 30%, transparent);
}

.map-view .territory-note input[type="range"]::-moz-range-track {
    block-size: 0.25rem;
    border-radius: 0.125rem;
    background: color-mix(in srgb, var(--surface) 30%, transparent);
}

.map-view .territory-note input[type="range"]::-moz-range-progress {
    block-size: 0.25rem;
    border-radius: 0.125rem;
    background: var(--surface);
}

.map-view .territory-note input[type="range"]::-webkit-slider-thumb {
    box-sizing: border-box;
    inline-size: 1.25rem;
    block-size: 1.25rem;
    margin-block-start: -0.5rem;
    border: 0.125rem solid var(--stage);
    border-radius: 50%;
    background: var(--surface);
    appearance: none;
}

.map-view .territory-note input[type="range"]::-moz-range-thumb {
    box-sizing: border-box;
    inline-size: 1.25rem;
    block-size: 1.25rem;
    border: 0.125rem solid var(--stage);
    border-radius: 50%;
    background: var(--surface);
}

.map-view .territory-note input[type="range"]:focus-visible,
.map-view .legend .toggle:focus-visible {
    outline: 0.125rem solid var(--surface);
    outline-offset: 0.125rem;
}

/* FocusTrail bubble */
.map-view .tooltip {
    position: absolute;
    inset-block-start: calc(var(--tip-y) + 0.75rem);
    inset-inline-start: calc(var(--tip-x) + 0.75rem);
    z-index: 3;
    display: grid;
    gap: 0.25rem;
    max-inline-size: 20rem;
    padding-block: 0.5rem;
    padding-inline: 0.625rem;
    border-radius: 0.5rem;
    background: var(--ink);
    box-shadow: var(--shadow-md);
    color: var(--surface);
    font-size: 0.75rem;
    line-height: 1.4;
    pointer-events: none;
}

.map-view .tooltip.flip-x {
    inset-inline-start: calc(var(--tip-x) - 0.75rem);
    translate: -100% 0;
}

.map-view .tooltip.flip-y {
    inset-block-start: calc(var(--tip-y) - 0.75rem);
    translate: 0 -100%;
}

.map-view .tooltip.flip-x.flip-y {
    translate: -100% -100%;
}

.map-view .tooltip .name {
    font-weight: 600;
}

.map-view .tooltip em {
    color: color-mix(in srgb, var(--surface) 75%, transparent);
    font-style: normal;
}

.map-view .tooltip .rows {
    display: grid;
    gap: 0.25rem;
    padding: 0;
    list-style: none;
}

.map-view .tooltip .rows li {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    min-inline-size: 0;
    white-space: nowrap;
}

.map-view .tooltip .label {
    overflow: hidden;
    text-overflow: ellipsis;
}

.map-view .tooltip .attributed {
    color: color-mix(in srgb, var(--surface) 75%, transparent);
    font-style: italic;
}

/* AnalysisCard .attribution */
.map-view .credits {
    margin: 0;
    color: var(--ink-muted);
    font-size: 0.6875rem;
}

.map-view .credits a {
    color: inherit;
}

.map-view button:focus-visible,
.map-view a:focus-visible,
.map-view input:focus-visible,
.map-view .timeline-box:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

@media (forced-colors: active) {
    .map-view .segmented button[aria-pressed="true"],
    .map-view .segments button[aria-pressed="true"] {
        outline: 0.125rem solid Highlight;
    }
}

@media (max-width: 80rem) {
    .map-view .workspace {
        grid-template-columns: minmax(0, 1fr) var(--explorer-side);
        grid-template-areas:
            "rail rail"
            "main side";
    }

    .map-view .skeleton .rail-block {
        display: none;
    }
}

@media (max-width: 48rem) {
    .map-view .workspace {
        grid-template-columns: minmax(0, 1fr);
        grid-template-areas:
            "rail"
            "main";
    }

    .map-view .skeleton .side-block {
        display: none;
    }

    .map-view .mode-switch {
        display: flex;
        box-sizing: border-box;
        inline-size: 100%;
        min-inline-size: 0;
    }

    .map-view .mode-switch > button,
    .map-view .mode-switch > :deep(.help-tip) {
        flex: 1 1 0;
        min-inline-size: 0;
    }

    .map-view .mode-switch button {
        inline-size: 100%;
        min-inline-size: 0;
        white-space: normal;
    }

    .map-view .tools {
        margin-inline-start: 0;
    }
}
</style>
