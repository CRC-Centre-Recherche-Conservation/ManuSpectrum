import { computed, ref } from "vue";
import { defineStore } from "pinia";

import {
    BASKET_LIMIT,
    freeSlots,
    kindOf,
    uniqueKeys,
} from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    nextFreeSlot,
    pinInSlots,
    unpinFromSlots,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import { isViewAvailable } from "@/manuspectrum/pages/AnalysisExplorer/views/registry.ts";

import type {
    FacetGroup,
    FacetKey,
    PeriodEvent,
    PeriodMatch,
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
    ListFilterKey,
    MaterialsGrouping,
    Overlay,
    PageSize,
    ToolKind,
    ToolWindow,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";
import type { FocusMode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

export const PAGE_SIZES: readonly PageSize[] = [10, 25, 50];

export const LIST_FILTER_KEYS: readonly ListFilterKey[] = [
    "place",
    "partType",
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
    component: "analyses",
};

export function emptyFilters(): Filters {
    return {
        q: "",
        grain: "documents",
        empty: false,
        size: PAGE_SIZES[0],
        partType: [],
        technique: [],
        part: [],
        material: [],
        colour: [],
        element: [],
        layer: [],
        project: [],
        operator: [],
        year: [],
        place: [],
        period: null,
        periodMatch: "overlap",
        periodEvent: "production",
        undated: false,
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

/** `tool:<kind>:<params>`: the parameters sorted and URL-encoded, `-` when there are none. */
export function toolWindowId(
    kind: ToolKind,
    params: Readonly<Record<string, string>>,
): string {
    const query = new URLSearchParams(
        Object.entries(params).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)),
    )
        .toString()
        .replaceAll("+", "%20");
    return `tool:${kind}:${query || "-"}`;
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
    /** Whether a document screen draws and lists the analyses the filters leave out (dimmed); kept from one document to the next. */
    const showOutside = ref(true);
    const layers = ref<LayerToggles>({
        points: true,
        zones: true,
        characterizations: true,
    });
    const overlays = ref<Record<string, Overlay>>({});
    const basket = ref<BasketItem[]>([]);
    /**
     * Compare: the tools open, and the focus (never saved): the nodes the
     * reader pinned to see what is linked to them, each at its slot
     * (index + 1; null is a hole left by an unpin, never trailing), and
     * whether it lights what relates to any of them or to all of them.
     */
    const compare = ref<{
        selection: (NodeId | null)[];
        mode: FocusMode;
        tools: ToolWindow[];
    }>({
        selection: [],
        mode: "any",
        tools: [],
    });
    /** Rail groups folded to their heading; not in the address. */
    const collapsedGroups = ref<FacetGroup[]>([]);
    /** How the Materials window of Compare groups its rows; for the tab only, not in the address. */
    const materialsGrouping = ref<MaterialsGrouping>("record");
    /**
     * Curves an XY window's legend eye hid, by window id then curve id
     * (`XyLegend`'s `LegendEntry.id`); for the tab only, never persisted and
     * never in the address. Independent of the focus: an eye-hidden curve
     * stays hidden whatever the focus links.
     */
    const hiddenCurves = ref<Record<string, string[]>>({});
    /** Whether the folio legend is unfolded; folded when the explorer opens. */
    const legendOpen = ref(false);

    const basketFree = computed(() => BASKET_LIMIT - basket.value.length);
    const activeFilterCount = computed(
        () =>
            countCorpusFilters(filters.value) +
            (view.value === "map" ? filters.value.eventType.length : 0),
    );

    function setFilter<K extends FilterKey>(key: K, value: Filters[K]): void {
        filters.value = { ...filters.value, [key]: normalized(key, value) };
    }

    /** Sets the period and its rule, event and undated option as the period facet reports them. */
    function setPeriod(change: {
        period: [number, number] | null;
        match: PeriodMatch;
        event: PeriodEvent;
        undated: boolean;
    }): void {
        setFilter("period", change.period);
        setFilter("periodMatch", change.match);
        setFilter("periodEvent", change.event);
        setFilter("undated", change.undated);
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
        const reset = emptyFilters();
        filters.value = {
            ...filters.value,
            [key]: reset[key],
            ...(key === "period"
                ? { periodMatch: reset.periodMatch, undated: reset.undated }
                : {}),
        };
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

    function setShowOutside(shown: boolean): void {
        showOutside.value = shown;
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

    function setMaterialsGrouping(grouping: MaterialsGrouping): void {
        materialsGrouping.value = grouping;
    }

    /** Hides or shows a curve of an XY window's legend, independent of the focus. */
    function toggleCurveVisibility(windowId: string, curveId: string): void {
        const current = hiddenCurves.value[windowId] ?? [];
        const next = current.includes(curveId)
            ? current.filter((id) => id !== curveId)
            : [...current, curveId];
        hiddenCurves.value = { ...hiddenCurves.value, [windowId]: next };
    }

    /** Shows every curve of an XY window the eye hid. */
    function showAllCurves(windowId: string): void {
        if (!hiddenCurves.value[windowId]) return;
        const next = { ...hiddenCurves.value };
        delete next[windowId];
        hiddenCurves.value = next;
    }

    /** Drops an XY window's eye-hidden curve ids `keep` refuses: a curve leaving the window loses its hidden state. */
    function pruneHiddenCurves(
        windowId: string,
        keep: (id: string) => boolean,
    ): void {
        const current = hiddenCurves.value[windowId];
        if (!current) return;
        const kept = current.filter(keep);
        if (kept.length === current.length) return;
        const next = { ...hiddenCurves.value };
        if (kept.length === 0) delete next[windowId];
        else next[windowId] = kept;
        hiddenCurves.value = next;
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

    /** Removes the held keys in one assignment, leaving their slots as holes; returns the removed items with their slots. */
    function removeManyFromBasket(keys: readonly string[]): BasketItem[] {
        const wanted = new Set(keys);
        const removed = basket.value.filter((item) => wanted.has(item.key));
        if (removed.length > 0) {
            basket.value = basket.value.filter((item) => !wanted.has(item.key));
        }
        return removed;
    }

    /**
     * Puts removed items back in one assignment, each at its own slot when
     * that slot is free, else in the lowest hole; items already held are
     * skipped and what exceeds the 30 places is dropped.
     */
    function restoreBasketItems(
        items: readonly BasketItem[],
    ): BasketLoadResult {
        const present = new Set(basket.value.map((item) => item.key));
        const fresh = items.filter((item, index) => {
            if (present.has(item.key)) return false;
            return items.findIndex((other) => other.key === item.key) === index;
        });
        const kept = fresh.slice(0, basketFree.value);
        const next = [...basket.value];
        const taken = new Set(next.map((item) => item.slot));
        const pending: BasketItem[] = [];
        for (const item of kept) {
            if (
                taken.has(item.slot) ||
                item.slot < 0 ||
                item.slot >= BASKET_LIMIT
            ) {
                pending.push(item);
            } else {
                taken.add(item.slot);
                next.push({ ...item });
            }
        }
        const holes = freeSlots(next, pending.length);
        pending.forEach((item, index) => {
            next.push({ ...item, slot: holes[index] });
        });
        if (kept.length > 0) basket.value = next;
        return {
            kept: kept.map((item) => item.key),
            truncated: fresh.length - kept.length,
        };
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

    /** Opens a tool once: the same kind with the same parameters is the same window. */
    function openTool(
        kind: ToolKind,
        params: Record<string, string> = {},
    ): string {
        const id = toolWindowId(kind, params);
        if (compare.value.tools.some((tool) => tool.id === id)) return id;
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

    /**
     * Pins a node in the lowest free slot of the focus, or unpins it when
     * it is there: its slot becomes a hole, trailing holes are trimmed, and
     * no other slot is renumbered. A pin while `FOCUS_MAX` nodes are pinned
     * changes nothing.
     */
    function toggleSelection(id: NodeId): void {
        const current = compare.value.selection;
        if (!current.includes(id) && nextFreeSlot(current) === null) return;
        compare.value = {
            ...compare.value,
            selection: current.includes(id)
                ? unpinFromSlots(current, (entry) => entry === id)
                : pinInSlots(current, id),
        };
    }

    /** Empties the focus and lights what relates to any pinned node again. */
    function clearSelection(): void {
        compare.value = { ...compare.value, selection: [], mode: "any" };
    }

    function setFocusMode(mode: FocusMode): void {
        if (compare.value.mode === mode) return;
        compare.value = { ...compare.value, mode };
    }

    /** Unpins the nodes `keep` refuses, leaving holes; returns them, in slot order. */
    function pruneSelection(keep: (id: NodeId) => boolean): NodeId[] {
        const dropped = compare.value.selection.filter(
            (id): id is NodeId => id !== null && !keep(id),
        );
        if (dropped.length > 0) {
            compare.value = {
                ...compare.value,
                selection: unpinFromSlots(
                    compare.value.selection,
                    (id) => !keep(id),
                ),
            };
        }
        return dropped;
    }

    return {
        view,
        corpusScreen,
        filters,
        document,
        documentOrigin,
        focus,
        folioView,
        showOutside,
        layers,
        overlays,
        basket,
        compare,
        collapsedGroups,
        materialsGrouping,
        hiddenCurves,
        legendOpen,
        basketFree,
        activeFilterCount,
        setFilter,
        setPeriod,
        setFacet,
        clearFilter,
        clearFilters,
        setView,
        setCorpusScreen,
        openDocument,
        setCanvas,
        focusOn,
        setFolioView,
        setShowOutside,
        setLayer,
        toggleGroup,
        setMaterialsGrouping,
        toggleCurveVisibility,
        showAllCurves,
        pruneHiddenCurves,
        setLegendOpen,
        addToBasket,
        addManyToBasket,
        removeFromBasket,
        removeManyFromBasket,
        restoreBasketItems,
        clearBasket,
        replaceBasket,
        mergeBasket,
        setOverlay,
        openTool,
        closeTool,
        toggleSelection,
        clearSelection,
        setFocusMode,
        pruneSelection,
    };
});

export type ExplorerStore = ReturnType<typeof useExplorerStore>;
