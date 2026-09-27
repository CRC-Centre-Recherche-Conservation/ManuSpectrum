<script setup lang="ts">
import {
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
    clearLayout,
    flowLayout,
    keepWindows,
    readLayout,
    readingOrder,
    sizeOf,
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
const ONE_COLUMN_MAX_WIDTH = 768;
const CELL_HEIGHT = "4rem";
const GAP = "0.5rem";

/**
 * The Compare windows on a gridstack grid. gridstack owns every window's
 * x, y, w, h: its `change` event writes the layout (`ms-explorer-layout-v1`,
 * 12 columns only), nothing here binds a position. The saved layout is read
 * once, when the grid mounts, and trimmed to the windows shown then; a window
 * that leaves and comes back while the grid is up gets its place again. With
 * nothing saved, gridstack places the windows (`autoPosition`); a window that
 * appears later goes under the others, without the focus, and is announced.
 * gridstack keeps the DOM in reading order, which the keyboard follows.
 */
const props = defineProps<{ windows: readonly CompareWindowSpec[] }>();

const emit = defineEmits<{
    (event: "close", payload: { id: string }): void;
}>();

const announce = inject(ANNOUNCE_KEY, () => undefined, false);

const { $gettext, $ngettext, interpolate } = useGettext();

const gridElement = ref<HTMLElement | null>(null);
/** Window ids in reading order, read from gridstack after each change. */
const order = ref<string[]>(props.windows.map((window) => window.id));
/** Each window's preset size, null once resized by hand. */
const sizes = ref<Record<string, WindowSize | null>>(
    Object.fromEntries(props.windows.map((window) => [window.id, window.size])),
);
const resizeTick = ref(0);

let grid: GridStack | null = null;
let saved: WindowLayout = {};
let saving = true;
let observer: ResizeObserver | null = null;
let resizeTimer: ReturnType<typeof setTimeout> | undefined;
let closing: { id: string; index: number } | null = null;

provide(WINDOW_RESIZE_KEY, readonly(resizeTick));

watch(
    () => props.windows.map((window) => window.id),
    (ids, previous) => {
        const gone = previous.filter((id) => !ids.includes(id));
        for (const id of gone) {
            const element = itemElement(id);
            if (grid && element) grid.removeWidget(element, false, true);
        }
        if (gone.length > 0) syncFromGrid();
        if (closing && gone.includes(closing.id)) {
            const index = closing.index;
            closing = null;
            void nextTick(() => focusWindowAt(index));
        }
    },
    { flush: "pre" },
);

watch(
    () => props.windows.map((window) => window.id),
    (ids, previous) => {
        const added = props.windows.filter(
            (window) => !previous.includes(window.id),
        );
        if (!grid || added.length === 0) return;
        for (const window of added) placeWindow(window, false);
        syncFromGrid();
        announce(
            interpolate(
                $ngettext(
                    "New window at the end: %{titles}",
                    "New windows at the end: %{titles}",
                    added.length,
                ),
                { titles: added.map((window) => window.title).join(", ") },
                true,
            ),
        );
    },
    { flush: "post" },
);

onMounted(() => {
    const element = gridElement.value;
    const created = element && GridStack.init(gridOptions(), element);
    if (!element || !created) return;
    grid = created;
    const stored = readLayout();
    saved = keepWindows(
        stored,
        props.windows.map((window) => window.id),
    );
    if (Object.keys(saved).length !== Object.keys(stored).length) {
        writeLayout(saved);
    }
    created.batchUpdate();
    for (const window of props.windows) placeWindow(window, true);
    created.batchUpdate(false);
    created.on("change", onGridChange);
    created.on("resizestop", scheduleResize);
    syncFromGrid();
    observer = new ResizeObserver(scheduleResize);
    observer.observe(element);
});

onBeforeUnmount(() => {
    observer?.disconnect();
    clearTimeout(resizeTimer);
    grid?.destroy(false);
    grid = null;
});

function gridOptions(): GridStackOptions {
    return {
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

function titleOf(id: string): string {
    return props.windows.find((window) => window.id === id)?.title ?? "";
}

/** Its saved place; else gridstack's choice when the grid opens, the end of the grid afterwards. */
function placeWindow(window: CompareWindowSpec, opening: boolean): void {
    const element = itemElement(window.id);
    if (!grid || !element) return;
    const box = saved[window.id];
    const preset = WINDOW_SIZES[window.size];
    let options: GridStackWidget;
    if (box) {
        options = { id: window.id, ...box };
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

function onGridChange(): void {
    syncFromGrid();
    if (!saving || grid?.getColumn() !== GRID_COLUMNS) return;
    const current: WindowLayout = {};
    for (const node of gridNodes()) current[node.id as string] = boxOf(node);
    saved = { ...saved, ...current };
    writeLayout(saved);
}

function applyLayout(layout: WindowLayout): void {
    if (!grid) return;
    grid.batchUpdate();
    for (const [id, box] of Object.entries(layout)) {
        const element = itemElement(id);
        if (element) grid.update(element, box);
    }
    grid.batchUpdate(false);
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

function focusWindowAt(index: number): void {
    const id = order.value[Math.min(index, order.value.length - 1)];
    const target = id
        ? itemElement(id)?.querySelector<HTMLElement>(".compare-window")
        : null;
    target?.focus();
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

function close(id: string): void {
    closing = { id, index: order.value.indexOf(id) };
    announce(
        interpolate($gettext("%{title} closed."), { title: titleOf(id) }, true),
    );
    emit("close", { id });
}

/** Empties the saved layout and lays the windows out again in their order, at their first size. */
function rearrange(): void {
    if (!grid) return;
    clearLayout();
    saved = {};
    saving = false;
    applyLayout(
        flowLayout(
            props.windows.map((window) => ({
                id: window.id,
                ...WINDOW_SIZES[window.size],
            })),
            grid.getColumn(),
        ),
    );
    saving = true;
    announce($gettext("Windows rearranged."));
}
</script>

<template>
    <div class="window-grid">
        <div class="toolbar">
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
                        @move="move(window.id, $event.step)"
                        @size-chosen="resize(window.id, $event.size)"
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
