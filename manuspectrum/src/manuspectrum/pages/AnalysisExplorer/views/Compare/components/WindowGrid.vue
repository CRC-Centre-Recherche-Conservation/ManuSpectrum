<script setup lang="ts">
import {
    computed,
    inject,
    nextTick,
    onBeforeUnmount,
    onMounted,
    provide,
    readonly,
    ref,
    watch,
} from "vue";
import { GridStack } from "gridstack";
import { useGettext } from "vue3-gettext";

import CompareWindow from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/CompareWindow.vue";

import {
    ANNOUNCE_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    GRID_COLUMNS,
    WINDOW_SIZES,
    clearBoxes,
    flowLayout,
    keepWindows,
    nearestBox,
    readFolded,
    readLayout,
    readingOrder,
    sizeOf,
    writeFolded,
    writeLayout,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";

import type {
    GridStackNode,
    GridStackOptions,
    GridStackWidget,
} from "gridstack";
import type {
    CompareWindowSpec,
    WindowBox,
    WindowLayout,
    WindowSize,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

const RESIZE_DEBOUNCE_MS = 150;
/** Rows of a window folded to its header (its controls may wrap on two lines). */
const FOLDED_ROWS = 2;
const ONE_COLUMN_MAX_WIDTH = 768;
const CELL_HEIGHT = "4rem";
const GAP = "0.5rem";

/**
 * The Compare windows on a gridstack grid. gridstack adopts none of the
 * rendered items (`auto: false`): each window is made a widget here, with
 * its id and its box. The grid has no gravity (`mode: "float"`), so a
 * window stays where it was put and an order set by « Move » or
 * « Rearrange » holds. gridstack owns every window's x, y, w, h afterwards:
 * its `change` event writes the layout (`ms-explorer-layout-v1`, 12 columns
 * only), nothing here binds a position. The saved layout is read once, when
 * the grid mounts, and trimmed to the windows shown then and the windows
 * `retained` names (hidden, kept with their place); a window that leaves
 * the grid loses its place unless `retained` names it. With nothing saved,
 * gridstack places the windows (`autoPosition`); a window that appears
 * later goes back to its place, else under the others, without the focus,
 * and is announced. A window that leaves the grid leaves no hole: the
 * windows under it move up (gridstack's `top` packing, run once), none
 * changes column. When the reader closed it, the focus goes to the window
 * nearest its place, without scrolling the page unless that window is
 * entirely off the screen; the grid keeps its height until the windows left
 * reach the bottom of the screen again (at once, or once the reader scrolls
 * up), so that the page does not shorten under the reader and move. Under 768 px the windows are listed on one
 * column, never saved; back on 12 columns, the saved places are put back.
 * « Rearrange » lays the windows shown out again, forgets every saved place
 * (the hidden windows', `retained`, included: they come back at the end)
 * and saves the new ones; the hidden, folded and open windows stay as they
 * are, and the announcement counts the windows that stay hidden. A folded window keeps
 * its header only (its content, once shown, stays mounted); the reader's
 * fold or unfold is saved with the layout and wins over the window's spec,
 * and a folded window's saved box keeps its unfolded height. gridstack
 * keeps the DOM in reading order, which the keyboard follows. Windows are
 * told to draw again (`WINDOW_RESIZE_KEY`) when the grid's width or a
 * window's size changes, not when a drag makes the grid taller. The
 * `toolbar` slot is laid before « Rearrange ».
 */
const props = withDefaults(
    defineProps<{
        windows: readonly CompareWindowSpec[];
        retained?: readonly string[];
    }>(),
    { retained: () => [] },
);

const emit = defineEmits<{
    (event: "close", payload: { id: string }): void;
}>();

const announce = inject(ANNOUNCE_KEY, () => undefined, false);

const { $gettext, $ngettext, interpolate } = useGettext();

const rootElement = ref<HTMLElement | null>(null);
const gridElement = ref<HTMLElement | null>(null);
/** The grid's height before a close, in px, kept until the page may shorten without moving. */
const heldHeight = ref<number | null>(null);
/** Window ids in reading order, read from gridstack after each change. */
const order = ref<string[]>(props.windows.map((window) => window.id));
/** Each window's preset size, null once resized by hand. */
const sizes = ref<Record<string, WindowSize | null>>(
    Object.fromEntries(props.windows.map((window) => [window.id, window.size])),
);
const resizeTick = ref(0);
/** The windows the reader folded or unfolded, as saved; read before the first render, so that a window opens as saved. */
let savedFolds: Record<string, boolean> = readFolded();
/** Whether each window that folds is folded: as the reader saved it, else as its spec says when it is placed; then as the reader sets it. */
const foldState = ref<Record<string, boolean>>(
    Object.fromEntries(
        props.windows.flatMap((window) =>
            window.folded === undefined
                ? []
                : [[window.id, savedFolds[window.id] ?? window.folded]],
        ),
    ),
);

let grid: GridStack | null = null;
let saved: WindowLayout = {};
let saving = true;
let observer: ResizeObserver | null = null;
/** The grid's content width last observed. */
let observedWidth: number | null = null;
/** The column count of the last `change` handled. */
let shownColumns = GRID_COLUMNS;
let resizeTimer: ReturnType<typeof setTimeout> | undefined;
/** The window the reader is closing, and its box then. */
let closing: { id: string; box: WindowBox } | null = null;

const heldStyle = computed(() =>
    heldHeight.value === null
        ? undefined
        : { minBlockSize: `${heldHeight.value}px` },
);

provide(WINDOW_RESIZE_KEY, readonly(resizeTick));

watch(
    () => props.windows.map((window) => window.id),
    (ids, previous) => {
        const gone = previous.filter((id) => !ids.includes(id));
        for (const id of gone) {
            const element = itemElement(id);
            if (grid && element) grid.removeWidget(element, false, true);
        }
        if (gone.length > 0) {
            closeHoles();
            syncFromGrid();
            forgetGone(gone);
        }
        if (closing && gone.includes(closing.id)) {
            const box = closing.box;
            closing = null;
            void nextTick(() => {
                focusNearest(box);
                releaseWhenFilled();
            });
        }
    },
    { flush: "pre" },
);

watch(
    () => props.retained,
    (retained, previous) => {
        const shown = props.windows.map((window) => window.id);
        forgetGone(
            previous.filter(
                (id) => !retained.includes(id) && !shown.includes(id),
            ),
        );
    },
);

watch(
    () => props.windows.map((window) => window.id),
    (ids, previous) => {
        const added = props.windows.filter(
            (window) => !previous.includes(window.id),
        );
        if (!grid || added.length === 0) return;
        const back = added.filter((window) => saved[window.id]);
        const fresh = added.filter((window) => !saved[window.id]);
        for (const window of added) placeWindow(window, false);
        syncFromGrid();
        if (back.length > 0) {
            announce(
                interpolate(
                    $ngettext(
                        "Window back in its place: %{titles}",
                        "Windows back in their places: %{titles}",
                        back.length,
                    ),
                    { titles: titlesOf(back) },
                    true,
                ),
            );
        }
        if (fresh.length > 0) {
            announce(
                interpolate(
                    $ngettext(
                        "New window at the end: %{titles}",
                        "New windows at the end: %{titles}",
                        fresh.length,
                    ),
                    { titles: titlesOf(fresh) },
                    true,
                ),
            );
        }
    },
    { flush: "post" },
);

onMounted(() => {
    const element = gridElement.value;
    const created = element && GridStack.init(gridOptions(), element);
    if (!element || !created) return;
    grid = created;
    const ids = [
        ...props.windows.map((window) => window.id),
        ...props.retained,
    ];
    const stored = readLayout();
    saved = keepWindows(stored, ids);
    if (Object.keys(saved).length !== Object.keys(stored).length) {
        writeLayout(saved);
    }
    const storedFolds = savedFolds;
    savedFolds = keepWindows(storedFolds, ids);
    if (Object.keys(savedFolds).length !== Object.keys(storedFolds).length) {
        writeFolded(savedFolds);
    }
    created.batchUpdate();
    for (const window of props.windows) placeWindow(window, true);
    created.batchUpdate(false);
    created.on("change", onGridChange);
    created.on("resizestop", scheduleResize);
    shownColumns = created.getColumn();
    syncFromGrid();
    observer = new ResizeObserver(onGridResized);
    observer.observe(element);
});

onBeforeUnmount(() => {
    releaseHeight();
    observer?.disconnect();
    clearTimeout(resizeTimer);
    grid?.destroy(false);
    grid = null;
});

function gridOptions(): GridStackOptions {
    return {
        auto: false,
        mode: "float",
        column: GRID_COLUMNS,
        cellHeight: CELL_HEIGHT,
        margin: GAP,
        handle: ".compare-window .grab",
        animate: !window.matchMedia?.("(prefers-reduced-motion: reduce)")
            .matches,
        columnOpts: {
            breakpoints: [{ w: ONE_COLUMN_MAX_WIDTH, c: 1 }],
            breakpointForWindow: true,
            layout: "list",
        },
    };
}

function itemElement(id: string): HTMLElement | null {
    const items = gridElement.value?.children ?? [];
    for (const item of items) {
        if (item instanceof HTMLElement && item.dataset.windowId === id) {
            return item;
        }
    }
    return null;
}

function specOf(id: string): CompareWindowSpec | undefined {
    return props.windows.find((window) => window.id === id);
}

function titleOf(id: string): string {
    return specOf(id)?.title ?? "";
}

function titlesOf(windows: readonly CompareWindowSpec[]): string {
    return windows.map((window) => window.title).join(", ");
}

/** Whether a window is folded to its header; null for a window that does not fold. */
function foldedOf(window: CompareWindowSpec): boolean | null {
    if (window.folded === undefined) return null;
    return foldState.value[window.id] ?? window.folded;
}

/** Its height unfolded: its saved box's, else its first size's. */
function unfoldedRows(window: CompareWindowSpec): number {
    return saved[window.id]?.h ?? WINDOW_SIZES[window.size].h;
}

/** Saves a fold or an unfold the reader asked for. */
function rememberFold(id: string, folded: boolean): void {
    savedFolds = { ...savedFolds, [id]: folded };
    writeFolded(savedFolds);
}

/** Its first size, as tall as its header when folded. */
function firstBox(window: CompareWindowSpec): Pick<WindowBox, "w" | "h"> {
    const preset = WINDOW_SIZES[window.size];
    return foldedOf(window) ? { w: preset.w, h: FOLDED_ROWS } : preset;
}

/** Forgets the places of the windows gone that `retained` does not name. */
function forgetGone(gone: readonly string[]): void {
    const forgotten = gone.filter(
        (id) =>
            (saved[id] || savedFolds[id] !== undefined) &&
            !props.retained.includes(id),
    );
    if (forgotten.length === 0) return;
    saved = keepWindows(
        saved,
        Object.keys(saved).filter((id) => !forgotten.includes(id)),
    );
    writeLayout(saved);
    savedFolds = keepWindows(
        savedFolds,
        Object.keys(savedFolds).filter((id) => !forgotten.includes(id)),
    );
    writeFolded(savedFolds);
}

/** Its saved place; else gridstack's choice when the grid opens, the end of the grid afterwards. */
function placeWindow(window: CompareWindowSpec, opening: boolean): void {
    const element = itemElement(window.id);
    if (!grid || !element) return;
    if (
        window.folded !== undefined &&
        foldState.value[window.id] === undefined
    ) {
        foldState.value = {
            ...foldState.value,
            [window.id]: savedFolds[window.id] ?? window.folded,
        };
    }
    const box = saved[window.id];
    const preset = firstBox(window);
    let options: GridStackWidget;
    if (box) {
        options = {
            id: window.id,
            ...box,
            ...(foldedOf(window) ? { h: FOLDED_ROWS } : {}),
        };
    } else if (opening) {
        options = { id: window.id, autoPosition: true, ...preset };
    } else {
        options = { id: window.id, x: 0, y: grid.getRow(), ...preset };
    }
    grid.makeWidget(element, options);
}

function gridNodes(): GridStackNode[] {
    if (!grid) return [];
    return grid
        .getGridItems()
        .map((element) => element.gridstackNode)
        .filter((node): node is GridStackNode => Boolean(node?.id));
}

function boxOf(node: GridStackNode): WindowBox {
    return { x: node.x ?? 0, y: node.y ?? 0, w: node.w ?? 1, h: node.h ?? 1 };
}

function syncFromGrid(): void {
    const nodes = gridNodes();
    const columns = grid?.getColumn() ?? GRID_COLUMNS;
    order.value = readingOrder(
        nodes.map((node) => ({ id: node.id as string, ...boxOf(node) })),
    ).map((box) => box.id);
    sizes.value = Object.fromEntries(
        nodes.map((node) => [node.id, sizeOf(boxOf(node), columns)]),
    );
}

/** What a window's box is saved as: a folded window keeps its unfolded height. */
function savedBoxOf(node: GridStackNode): WindowBox {
    const box = boxOf(node);
    const window = specOf(node.id as string);
    return window && foldedOf(window)
        ? { ...box, h: unfoldedRows(window) }
        : box;
}

/**
 * Saves what gridstack reports on 12 columns. A change of column count is
 * never saved: back on 12 columns, the saved places are put back once
 * gridstack has ended its own relayout.
 */
function onGridChange(): void {
    syncFromGrid();
    const columns = grid?.getColumn() ?? GRID_COLUMNS;
    if (columns !== shownColumns) {
        shownColumns = columns;
        scheduleResize();
        if (columns === GRID_COLUMNS) queueMicrotask(restoreSaved);
        return;
    }
    if (saving && columns === GRID_COLUMNS) saveGrid();
}

function saveGrid(): void {
    const current: WindowLayout = {};
    for (const node of gridNodes()) {
        current[node.id as string] = savedBoxOf(node);
    }
    saved = { ...saved, ...current };
    writeLayout(saved);
}

/** The saved places of the windows shown, a folded window as tall as its header. */
function restoreSaved(): void {
    if (!grid || grid.getColumn() !== GRID_COLUMNS) return;
    const layout: WindowLayout = {};
    for (const window of props.windows) {
        const box = saved[window.id];
        if (box) {
            layout[window.id] = foldedOf(window)
                ? { ...box, h: FOLDED_ROWS }
                : box;
        }
    }
    saving = false;
    applyLayout(layout);
    saving = true;
}

/** Moves the windows to their boxes in one go (`load` takes the windows out before it puts them back, so none pushes another). */
function applyLayout(layout: WindowLayout): void {
    if (!grid || Object.keys(layout).length === 0) return;
    grid.load(
        Object.entries(layout).map(([id, box]) => ({ id, ...box })),
        false,
    );
}

function onGridResized(entries: readonly ResizeObserverEntry[]): void {
    const width = entries.at(-1)?.contentRect.width;
    if (width === undefined || width === observedWidth) return;
    observedWidth = width;
    scheduleResize();
}

function scheduleResize(): void {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
        resizeTick.value += 1;
    }, RESIZE_DEBOUNCE_MS);
}

function positionOf(id: string): number {
    return order.value.indexOf(id) + 1;
}

/** Moves the windows up into the room left free, once (gridstack's `top` mode), then lets them float again. */
function closeHoles(): void {
    grid?.mode("top");
    grid?.mode("float");
}

/** Keeps the grid as tall as it is while a window closes. */
function holdHeight(): void {
    const element = rootElement.value;
    if (!element) return;
    heldHeight.value = element.offsetHeight;
    window.addEventListener("scroll", releaseWhenFilled, { passive: true });
}

function releaseHeight(): void {
    heldHeight.value = null;
    window.removeEventListener("scroll", releaseWhenFilled);
}

/** Lets the grid shorten once its windows reach the bottom of the screen: the room freed is then below it. */
function releaseWhenFilled(): void {
    if (heldHeight.value === null) return;
    const bottom = gridElement.value?.getBoundingClientRect().bottom;
    if (bottom === undefined || bottom >= window.innerHeight) releaseHeight();
}

/** Focuses the window nearest `box`; the page scrolls only when that window is entirely off the screen. */
function focusNearest(box: WindowBox): void {
    const nearest = nearestBox(
        box,
        gridNodes().map((node) => ({ id: node.id as string, ...boxOf(node) })),
    );
    const target = nearest
        ? itemElement(nearest.id)?.querySelector<HTMLElement>(".compare-window")
        : null;
    if (!target) return;
    target.focus({ preventScroll: true });
    const { top, bottom } = target.getBoundingClientRect();
    if (bottom <= 0 || top >= window.innerHeight) {
        target.scrollIntoView?.({ block: "nearest" });
    }
}

function move(id: string, step: -1 | 1): void {
    if (!grid) return;
    const index = order.value.indexOf(id);
    const target = index + step;
    if (index < 0 || target < 0 || target >= order.value.length) return;
    const next = [...order.value];
    [next[index], next[target]] = [next[target], next[index]];
    const boxes = new Map(
        gridNodes().map((node) => [node.id as string, boxOf(node)]),
    );
    applyLayout(
        flowLayout(
            next.map((windowId) => ({
                id: windowId,
                w: boxes.get(windowId)?.w ?? 1,
                h: boxes.get(windowId)?.h ?? 1,
            })),
            grid.getColumn(),
        ),
    );
    announce(
        interpolate(
            $gettext("%{title}: %{position} of %{total}"),
            {
                title: titleOf(id),
                position: positionOf(id),
                total: order.value.length,
            },
            true,
        ),
    );
    itemElement(id)
        ?.querySelector<HTMLElement>(
            `[data-action="${step < 0 ? "move-before" : "move-after"}"]`,
        )
        ?.focus();
}

function resize(id: string, size: WindowSize): void {
    const element = itemElement(id);
    if (!grid || !element) return;
    const preset = WINDOW_SIZES[size];
    if (foldState.value[id]) {
        foldState.value = { ...foldState.value, [id]: false };
        rememberFold(id, false);
    }
    grid.update(element, {
        w: Math.min(preset.w, grid.getColumn()),
        h: preset.h,
    });
    announce(
        interpolate(
            $gettext("%{title}: size %{size}"),
            { title: titleOf(id), size },
            true,
        ),
    );
    scheduleResize();
}

/** Folds a window to its header, or unfolds it to its saved height. */
function toggleFold(id: string): void {
    const window = specOf(id);
    const element = itemElement(id);
    if (!grid || !window || !element || foldedOf(window) === null) return;
    const folded = !foldedOf(window);
    foldState.value = { ...foldState.value, [id]: folded };
    rememberFold(id, folded);
    grid.update(element, {
        h: folded ? FOLDED_ROWS : unfoldedRows(window),
    });
    announce(
        interpolate(
            folded
                ? $gettext("%{title}: folded")
                : $gettext("%{title}: unfolded"),
            { title: window.title },
            true,
        ),
    );
    scheduleResize();
}

/** The parent answers the request: hides the window, or closes the tool, and says so. */
function close(id: string): void {
    const node = gridNodes().find((entry) => entry.id === id);
    closing = node ? { id, box: boxOf(node) } : null;
    holdHeight();
    emit("close", { id });
}

/**
 * Lays the windows shown out again in their order, at their first size (a
 * folded window as tall as its header), forgets every saved place and saves
 * the new ones (on 12 columns); the windows are told their new size.
 */
function rearrange(): void {
    if (!grid) return;
    releaseHeight();
    saving = false;
    clearBoxes();
    saved = {};
    applyLayout(
        flowLayout(
            props.windows.map((window) => ({
                id: window.id,
                ...firstBox(window),
            })),
            grid.getColumn(),
        ),
    );
    saving = true;
    if (grid.getColumn() === GRID_COLUMNS) saveGrid();
    scheduleResize();
    const stayHidden = props.retained.length;
    announce(
        stayHidden === 0
            ? $gettext("Windows rearranged.")
            : interpolate(
                  $ngettext(
                      "Windows rearranged. %{n} window stays hidden.",
                      "Windows rearranged. %{n} windows stay hidden.",
                      stayHidden,
                  ),
                  { n: stayHidden },
                  true,
              ),
    );
}
</script>

<template>
    <div
        ref="rootElement"
        class="window-grid"
        :style="heldStyle"
    >
        <div class="toolbar">
            <slot name="toolbar" />
            <button
                type="button"
                class="rearrange"
                @click="rearrange"
            >
                <span>{{ $gettext("Rearrange") }}</span>
            </button>
        </div>
        <div
            ref="gridElement"
            class="grid-stack"
        >
            <div
                v-for="window in windows"
                :key="window.id"
                class="grid-stack-item"
                :data-window-id="window.id"
            >
                <div class="grid-stack-item-content">
                    <CompareWindow
                        :title="window.title"
                        :position="positionOf(window.id)"
                        :total="windows.length"
                        :size="sizes[window.id] ?? null"
                        :folded="foldedOf(window)"
                        @move="move(window.id, $event.step)"
                        @size-chosen="resize(window.id, $event.size)"
                        @fold-toggled="toggleFold(window.id)"
                        @close="close(window.id)"
                    >
                        <slot :window="window" />
                    </CompareWindow>
                </div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.window-grid {
    display: grid;
    gap: 0.5rem;
}

.window-grid .toolbar {
    display: flex;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 0.5rem;
}

.window-grid .rearrange {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.window-grid .rearrange:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.window-grid .grid-stack-item-content {
    overflow: visible;
}
</style>
