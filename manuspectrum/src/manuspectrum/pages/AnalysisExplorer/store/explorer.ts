import { computed, ref } from "vue";
import { defineStore } from "pinia";

import {
    BASKET_LIMIT,
    freeSlots,
    kindOf,
    uniqueKeys,
} from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { isViewAvailable } from "@/manuspectrum/pages/AnalysisExplorer/views/registry.ts";

import type {
    FacetGroup,
    FacetKey,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    BasketAddResult,
    BasketItem,
    BasketLoadResult,
    CorpusScreen,
    DocumentOrigin,
    DocumentState,
    ExplorerView,
    FilterKey,
    Filters,
    Focus,
    FolioView,
    ItemKey,
    LayerToggles,
    ColourLevel,
    ListFilterKey,
    Overlay,
    PageSize,
    ToolFilters,
    ToolKind,
    ToolWindow,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export const PAGE_SIZES: readonly PageSize[] = [10, 25, 50];

export const LIST_FILTER_KEYS: readonly ListFilterKey[] = [
    "partType",
    "partColour",
    "technique",
    "part",
    "material",
    "colour",
    "element",
    "layer",
    "project",
    "operator",
];

const FOLIO_VIEW_OF: Partial<Record<Focus["kind"], FolioView>> = {
    analysis: "analyses",
    characterization: "characterizations",
    sample: "samples",
};

export function emptyFilters(): Filters {
    return {
        q: "",
        grain: "documents",
        empty: false,
        size: PAGE_SIZES[0],
        partType: [],
        partColour: [],
        technique: [],
        part: [],
        material: [],
        colour: [],
        element: [],
        layer: [],
        project: [],
        operator: [],
        year: [],
        place: null,
        period: null,
        eventType: [],
    };
}

/** The facet values the filters hold, by facet key (years as text, as the facets name them). */
export function selectedFacets(
    filters: Filters,
): Partial<Record<FacetKey, string[]>> {
    const selected: Partial<Record<FacetKey, string[]>> = {
        year: filters.year.map(String),
    };
    for (const key of LIST_FILTER_KEYS) selected[key] = filters[key];
    return selected;
}

function emptyToolFilters(): ToolFilters {
    return { element: null, cell: null, pair: null };
}

/** Filters that restrict Corpus results; `eventType` (Map only) and the display options (grain, empty, size) are not among them. */
export function hasActiveFilters(filters: Filters): boolean {
    return countCorpusFilters(filters) > 0;
}

function countCorpusFilters(filters: Filters): number {
    const listed = LIST_FILTER_KEYS.reduce(
        (total, key) => total + filters[key].length,
        0,
    );
    return (
        listed +
        filters.year.length +
        (filters.q ? 1 : 0) +
        (filters.place ? 1 : 0) +
        (filters.period ? 1 : 0)
    );
}

function normalized<K extends FilterKey>(
    key: K,
    value: Filters[K],
): Filters[K] {
    if (key === "year") {
        return [...new Set(value as number[])].sort(
            (a, b) => a - b,
        ) as Filters[K];
    }
    if (Array.isArray(value)) {
        return [...new Set(value as string[])].sort() as Filters[K];
    }
    if (typeof value === "string") {
        return value.trim() as Filters[K];
    }
    return value;
}

export const useExplorerStore = defineStore("explorer", () => {
    const view = ref<ExplorerView>("corpus");
    const corpusScreen = ref<CorpusScreen>("home");
    const filters = ref<Filters>(emptyFilters());
    const document = ref<DocumentState | null>(null);
    const documentOrigin = ref<DocumentOrigin>("home");
    const focus = ref<Focus | null>(null);
    const folioView = ref<FolioView>("analyses");
    const layers = ref<LayerToggles>({
        points: true,
        zones: true,
        characterizations: true,
    });
    const overlays = ref<Record<string, Overlay>>({});
    const basket = ref<BasketItem[]>([]);
    const compare = ref<{ toolFilters: ToolFilters; tools: ToolWindow[] }>({
        toolFilters: emptyToolFilters(),
        tools: [],
    });
    /** Rail groups folded to their heading; not in the address. */
    const collapsedGroups = ref<FacetGroup[]>([]);
    /** Which colour facet the rail's Colour toggle shows; not in the address. */
    const colourLevel = ref<ColourLevel>("colour");
    /** Whether the folio legend is unfolded; folded when the explorer opens. */
    const legendOpen = ref(false);
    let toolCounter = 0;

    const basketFree = computed(() => BASKET_LIMIT - basket.value.length);
    const activeFilterCount = computed(
        () =>
            countCorpusFilters(filters.value) +
            (view.value === "map" ? filters.value.eventType.length : 0),
    );

    function setFilter<K extends FilterKey>(key: K, value: Filters[K]): void {
        filters.value = { ...filters.value, [key]: normalized(key, value) };
    }

    function clearFilter(key: FilterKey, value?: string | number): void {
        const current = filters.value[key];
        if (value !== undefined && Array.isArray(current)) {
            const remaining = (current as (string | number)[]).filter(
                (entry) => entry !== value,
            );
            filters.value = { ...filters.value, [key]: remaining };
            return;
        }
        filters.value = { ...filters.value, [key]: emptyFilters()[key] };
    }

    function clearFilters(): void {
        filters.value = { ...emptyFilters(), ...displayOptions() };
    }

    function displayOptions(): Pick<Filters, "grain" | "empty" | "size"> {
        const { grain, empty, size } = filters.value;
        return { grain, empty, size };
    }

    function setView(next: ExplorerView): void {
        if (isViewAvailable(next)) {
            view.value = next;
        }
    }

    /**
     * Leaves the document screen for another Corpus screen; the document
     * screen is reached only through `openDocument`. The home screen carries
     * no Corpus filter: going there clears them, keeping the display options
     * (grain, documents without analyses, page size) and the Map's event types.
     */
    function setCorpusScreen(screen: CorpusScreen): void {
        if (screen === "document") {
            return;
        }
        if (screen === "home") {
            filters.value = {
                ...emptyFilters(),
                ...displayOptions(),
                eventType: filters.value.eventType,
            };
        }
        corpusScreen.value = screen;
        document.value = null;
        focus.value = null;
        folioView.value = "analyses";
    }

    /** Opens a document screen, remembering the Corpus screen it was opened from. */
    function openDocument(id: string, canvas: string | null = null): void {
        if (corpusScreen.value !== "document") {
            documentOrigin.value = corpusScreen.value;
        }
        view.value = "corpus";
        corpusScreen.value = "document";
        document.value = { id, canvas };
        focus.value = null;
        folioView.value = "analyses";
    }

    /** Changes the page of the open document; does nothing outside a document. */
    function setCanvas(canvas: string | null): void {
        if (document.value) {
            document.value = { ...document.value, canvas };
        }
    }

    /** Opens an analysis, identified material or sample and shows the folio view that draws it; clearing or a file focus keeps the view. */
    function focusOn(next: Focus | null): void {
        focus.value = next;
        const shown = next ? FOLIO_VIEW_OF[next.kind] : undefined;
        if (shown) folioView.value = shown;
    }

    function setFolioView(next: FolioView): void {
        folioView.value = next;
    }

    /** A facet's selected values from the rail; year values are read as integers. */
    function setFacet(key: FacetKey, ids: string[]): void {
        if (key === "year") {
            setFilter(
                "year",
                ids.map(Number).filter((year) => Number.isInteger(year)),
            );
        } else {
            setFilter(key, ids);
        }
    }

    function toggleGroup(group: FacetGroup): void {
        collapsedGroups.value = collapsedGroups.value.includes(group)
            ? collapsedGroups.value.filter((entry) => entry !== group)
            : [...collapsedGroups.value, group];
    }

    function setColourLevel(level: ColourLevel): void {
        colourLevel.value = level;
    }

    function setLegendOpen(open: boolean): void {
        legendOpen.value = open;
    }

    function setLayer(key: keyof LayerToggles, on: boolean): void {
        layers.value = { ...layers.value, [key]: on };
    }

    /** Adds every new key or none: an invalid key or a batch larger than the free places refuses the whole batch. */
    function addManyToBasket(keys: readonly string[]): BasketAddResult {
        const { keys: wanted, invalid } = uniqueKeys(keys);
        if (invalid > 0) {
            return {
                added: [],
                refused: "invalid",
                needed: wanted.length,
                free: basketFree.value,
            };
        }
        const present = new Set(basket.value.map((item) => item.key));
        const fresh = wanted.filter((key) => !present.has(key));
        if (fresh.length > basketFree.value) {
            return {
                added: [],
                refused: "full",
                needed: fresh.length,
                free: basketFree.value,
            };
        }
        const slots = freeSlots(basket.value, fresh.length);
        basket.value = [
            ...basket.value,
            ...fresh.map((key, index) => ({
                key,
                kind: kindOf(key),
                slot: slots[index],
            })),
        ];
        return {
            added: fresh,
            refused: null,
            needed: fresh.length,
            free: basketFree.value,
        };
    }

    function addToBasket(key: ItemKey): BasketAddResult {
        return addManyToBasket([key]);
    }

    function removeFromBasket(key: ItemKey): void {
        basket.value = basket.value.filter((item) => item.key !== key);
    }

    function clearBasket(): void {
        basket.value = [];
    }

    /** Replaces the Selection with the first 30 valid keys, in slots A1 onwards; invalid keys are dropped. */
    function replaceBasket(keys: readonly string[]): BasketLoadResult {
        const { keys: wanted } = uniqueKeys(keys);
        const kept = wanted.slice(0, BASKET_LIMIT);
        basket.value = kept.map((key, slot) => ({
            key,
            kind: kindOf(key),
            slot,
        }));
        return { kept, truncated: wanted.length - kept.length };
    }

    /** Adds the new valid keys into the free slots, keeping existing items where they are. */
    function mergeBasket(keys: readonly string[]): BasketLoadResult {
        const present = new Set(basket.value.map((item) => item.key));
        const fresh = uniqueKeys(keys).keys.filter((key) => !present.has(key));
        const kept = fresh.slice(0, basketFree.value);
        const slots = freeSlots(basket.value, kept.length);
        basket.value = [
            ...basket.value,
            ...kept.map((key, index) => ({
                key,
                kind: kindOf(key),
                slot: slots[index],
            })),
        ];
        return { kept, truncated: fresh.length - kept.length };
    }

    function setOverlay(key: string, overlay: Overlay | null): void {
        const next = { ...overlays.value };
        if (overlay === null) {
            delete next[key];
        } else {
            next[key] = overlay;
        }
        overlays.value = next;
    }

    function openTool(
        kind: ToolKind,
        params: Record<string, string> = {},
    ): string {
        toolCounter += 1;
        const id = `${kind}-${toolCounter}`;
        compare.value = {
            ...compare.value,
            tools: [...compare.value.tools, { id, kind, params }],
        };
        return id;
    }

    function closeTool(id: string): void {
        compare.value = {
            ...compare.value,
            tools: compare.value.tools.filter((tool) => tool.id !== id),
        };
    }

    function setToolFilter<K extends keyof ToolFilters>(
        key: K,
        value: ToolFilters[K],
    ): void {
        compare.value = {
            ...compare.value,
            toolFilters: { ...compare.value.toolFilters, [key]: value },
        };
    }

    function clearToolFilters(): void {
        compare.value = { ...compare.value, toolFilters: emptyToolFilters() };
    }

    return {
        view,
        corpusScreen,
        filters,
        document,
        documentOrigin,
        focus,
        folioView,
        layers,
        overlays,
        basket,
        compare,
        collapsedGroups,
        colourLevel,
        legendOpen,
        basketFree,
        activeFilterCount,
        setFilter,
        setFacet,
        clearFilter,
        clearFilters,
        setView,
        setCorpusScreen,
        openDocument,
        setCanvas,
        focusOn,
        setFolioView,
        setLayer,
        toggleGroup,
        setColourLevel,
        setLegendOpen,
        addToBasket,
        addManyToBasket,
        removeFromBasket,
        clearBasket,
        replaceBasket,
        mergeBasket,
        setOverlay,
        openTool,
        closeTool,
        setToolFilter,
        clearToolFilters,
    };
});

export type ExplorerStore = ReturnType<typeof useExplorerStore>;
