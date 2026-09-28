import { vi } from "vitest";

import type {
    GridItemHTMLElement,
    GridStackNode,
    GridStackOptions,
    GridStackWidget,
} from "gridstack";

type Handler = (event: Event, nodes: GridStackNode[]) => void;
type Box = { x: number; y: number; w: number; h: number };

const ITEM_CLASS = "grid-stack-item";

function overlaps(a: Box, b: Box): boolean {
    return (
        a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
    );
}

function boxOf(node: GridStackNode): Box {
    return { x: node.x ?? 0, y: node.y ?? 0, w: node.w ?? 1, h: node.h ?? 1 };
}

function readingOrder(nodes: GridStackNode[]): GridStackNode[] {
    return [...nodes].sort(
        (a, b) => (a.y ?? 0) - (b.y ?? 0) || (a.x ?? 0) - (b.x ?? 0),
    );
}

/**
 * gridstack 14 without drag and drop, for specs:
 * `vi.mock("gridstack", async () => (await import("…/testing/gridstack.ts")).gridstackModule())`.
 * It mirrors the behaviours of `node_modules/gridstack/dist/gridstack.js`
 * and `gridstack-engine.js` a component can depend on, each marked with
 * the line it copies; drag, resize handles, collisions pushing items down
 * and the layout caches of other column counts are left out.
 */
export class FakeGridStack {
    static instances: FakeGridStack[] = [];

    static init(
        options: GridStackOptions,
        element: HTMLElement,
    ): FakeGridStack {
        const grid = new FakeGridStack(options, element);
        FakeGridStack.instances.push(grid);
        return grid;
    }

    readonly options: GridStackOptions;
    readonly el: HTMLElement;
    private nodes: GridStackNode[] = [];
    private handlers = new Map<string, Handler[]>();
    private batching = false;
    private dirty = false;
    private columns: number;
    /** The widths of the widest layout, kept when the column count goes down (engine `cacheLayout`, gridstack-engine.js:1310). */
    private widths = new Map<GridStackNode, number>();

    constructor(options: GridStackOptions, element: HTMLElement) {
        this.options = options;
        this.el = element;
        this.columns = typeof options.column === "number" ? options.column : 12;
        // gridstack.js:298-302: unless `auto: false`, the grid adopts every
        // item already in the DOM, placed from its `gs-*` attributes (none:
        // first empty cell, 1×1, no id).
        if (options.auto !== false) {
            for (const item of this.getGridItems()) {
                const node: GridStackNode = { el: item, w: 1, h: 1 };
                this.findEmptyPosition(node);
                item.gridstackNode = node;
                this.nodes.push(node);
            }
        }
    }

    /** gridstack.js:1178: an element that already holds a node is returned untouched, the options ignored. */
    makeWidget = vi.fn(
        (element: HTMLElement, options: GridStackWidget = {}): HTMLElement => {
            const item = element as GridItemHTMLElement;
            if (item.gridstackNode) return element;
            const node: GridStackNode = {
                ...options,
                el: item,
                w: Math.min(options.w ?? 1, this.columns),
                h: options.h ?? 1,
            };
            if (
                options.autoPosition ||
                options.x === undefined ||
                options.y === undefined
            ) {
                this.findEmptyPosition(node);
            } else {
                node.x = Math.min(options.x, this.columns - (node.w ?? 1));
            }
            item.gridstackNode = node;
            this.nodes.push(node);
            this.changed();
            return element;
        },
    );

    update = vi.fn(
        (element: HTMLElement, options: GridStackWidget): FakeGridStack => {
            const node = (element as GridItemHTMLElement).gridstackNode;
            if (node) Object.assign(node, options);
            this.changed();
            return this;
        },
    );

    /** gridstack.js:653 with `addRemove` false: the items named by id take their boxes, in one batch. */
    load = vi.fn(
        (items: GridStackWidget[], _addRemove?: boolean): FakeGridStack => {
            for (const item of items) {
                const node = this.nodes.find((entry) => entry.id === item.id);
                if (!node) continue;
                const { x, y, w, h } = item;
                Object.assign(node, { x, y, w, h });
            }
            this.changed();
            return this;
        },
    );

    removeWidget = vi.fn((element: HTMLElement): FakeGridStack => {
        const item = element as GridItemHTMLElement;
        this.nodes = this.nodes.filter((node) => node !== item.gridstackNode);
        delete item.gridstackNode;
        this.changed();
        return this;
    });

    batchUpdate = vi.fn((flag = true): FakeGridStack => {
        this.batching = flag;
        if (!flag && this.dirty) this.fireChange();
        return this;
    });

    destroy = vi.fn((): FakeGridStack => this);

    /** gridstack.js:1019: the grid's item children, in DOM order. */
    getGridItems(): GridItemHTMLElement[] {
        return [...this.el.children].filter(
            (child): child is GridItemHTMLElement =>
                child instanceof HTMLElement &&
                child.classList.contains(ITEM_CLASS),
        );
    }

    /**
     * gridstack.js:1077 and the engine's `set mode` (gridstack-engine.js:405):
     * a mode other than `float` packs the items at once (`_packNodes`,
     * gridstack-engine.js:440); `change` fires only when an item moved
     * (`_triggerChangeEvent`, gridstack.js:1744, reads the dirty nodes).
     */
    mode = vi.fn((mode: GridStackOptions["mode"]): FakeGridStack => {
        if (this.options.mode === mode) return this;
        this.options.mode = mode;
        if (mode === "float") return this;
        const before = this.nodes.map((node) => node.y);
        this.pack();
        if (this.nodes.some((node, index) => node.y !== before[index])) {
            this.trigger("change");
        }
        return this;
    });

    getMode(): GridStackOptions["mode"] {
        return this.options.mode ?? "top";
    }

    getColumn(): number {
        return this.columns;
    }

    getRow(): number {
        return Math.max(
            0,
            ...this.nodes.map((node) => (node.y ?? 0) + (node.h ?? 1)),
        );
    }

    on(name: string, handler: Handler): FakeGridStack {
        for (const event of name.split(" ")) {
            this.handlers.set(event, [
                ...(this.handlers.get(event) ?? []),
                handler,
            ]);
        }
        return this;
    }

    off(name: string): FakeGridStack {
        this.handlers.delete(name);
        return this;
    }

    /**
     * Spec helper: what a breakpoint does (`checkDynamicColumn` → `column(c,
     * columnOpts.layout)`, gridstack.js:893, 972). With the `list` layout the
     * engine sorts the items in reading order, gives each its width of the
     * widest layout it saw, and flows them one after the other
     * (`columnChanged`, gridstack-engine.js:1205); `change` fires either way.
     */
    setColumns(columns: number): void {
        const previous = this.columns;
        if (columns === previous) return;
        if (columns < previous) {
            for (const node of this.nodes) {
                if (!this.widths.has(node)) this.widths.set(node, node.w ?? 1);
            }
        }
        this.columns = columns;
        const layout = this.options.columnOpts?.layout;
        const ordered = readingOrder(this.nodes);
        let after: GridStackNode | null = null;
        const placed: GridStackNode[] = [];
        for (const node of ordered) {
            const widest = this.widths.get(node) ?? node.w ?? 1;
            node.w = Math.min(widest, columns);
            if (layout === "list" || layout === "compact") {
                this.findEmptyPosition(node, placed, after);
            } else {
                node.x = Math.min(node.x ?? 0, columns - node.w);
            }
            placed.push(node);
            after = node;
        }
        if (columns >= previous) this.widths.clear();
        this.fireChange();
    }

    /** Spec helper: fires an event with every node, as a drag or a resize ends. */
    trigger(name: string): void {
        const nodes = [...this.nodes];
        for (const handler of this.handlers.get(name) ?? []) {
            handler(new Event(name), nodes);
        }
    }

    /** gridstack-engine.js:752: the first free cell in row-major order, from just past `after`. */
    private findEmptyPosition(
        node: GridStackNode,
        others: GridStackNode[] = this.nodes,
        after: GridStackNode | null = null,
    ): void {
        const w = Math.min(node.w ?? 1, this.columns);
        const h = node.h ?? 1;
        const start = after
            ? (after.y ?? 0) * this.columns + (after.x ?? 0) + (after.w ?? 1)
            : 0;
        for (let cell = start; ; cell += 1) {
            const x = cell % this.columns;
            const y = Math.floor(cell / this.columns);
            if (x + w > this.columns) continue;
            const box = { x, y, w, h };
            if (
                !others.some(
                    (other) => other !== node && overlaps(box, boxOf(other)),
                )
            ) {
                Object.assign(node, { x, y, w });
                delete node.autoPosition;
                return;
            }
        }
    }

    /**
     * gridstack-engine.js:440 (`_packNodes`): out of a batch, in the default
     * `top` mode, every item in reading order moves up while nothing is in
     * the way; `float` leaves them where they are.
     */
    private pack(): void {
        const mode = this.options.mode ?? "top";
        if (mode !== "top") return;
        const ordered = readingOrder(this.nodes);
        for (const node of ordered) {
            while ((node.y ?? 0) > 0) {
                const up = { ...boxOf(node), y: (node.y ?? 0) - 1 };
                if (
                    ordered.some(
                        (other) => other !== node && overlaps(up, boxOf(other)),
                    )
                ) {
                    break;
                }
                node.y = up.y;
            }
        }
    }

    private changed(): void {
        if (this.batching) {
            this.dirty = true;
        } else {
            this.fireChange();
        }
    }

    /** gridstack.js:762, 1744: `change` fires when a batch ends or at once, after the items are packed. */
    private fireChange(): void {
        this.dirty = false;
        this.pack();
        this.trigger("change");
    }
}

/** The grid a spec's component created last. */
export function lastGrid(): FakeGridStack {
    const grid = FakeGridStack.instances.at(-1);
    if (!grid) throw new Error("no grid was created");
    return grid;
}

export function resetFakeGrids(): void {
    FakeGridStack.instances = [];
}

export function gridstackModule(): { GridStack: typeof FakeGridStack } {
    return { GridStack: FakeGridStack };
}
