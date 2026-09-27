import { vi } from "vitest";

import type {
    GridItemHTMLElement,
    GridStackNode,
    GridStackOptions,
    GridStackWidget,
} from "gridstack";

type Handler = (event: Event, nodes: GridStackNode[]) => void;

/**
 * gridstack without layout or drag and drop, for specs:
 * `vi.mock("gridstack", async () => (await import("…/testing/gridstack.ts")).gridstackModule())`.
 * It keeps each widget's node on its element as gridstack does, places an
 * `autoPosition` widget under the others, and fires `change` like gridstack:
 * at once, or when a batch ends.
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
    private items: GridItemHTMLElement[] = [];
    private handlers = new Map<string, Handler[]>();
    private batching = false;
    private dirty = false;
    private columns: number;

    constructor(options: GridStackOptions, element: HTMLElement) {
        this.options = options;
        this.el = element;
        this.columns = typeof options.column === "number" ? options.column : 12;
    }

    makeWidget = vi.fn(
        (element: HTMLElement, options: GridStackWidget = {}): HTMLElement => {
            const item = element as GridItemHTMLElement;
            const node: GridStackNode = { ...options, el: item };
            if (options.autoPosition) {
                node.x = 0;
                node.y = this.getRow();
            }
            item.gridstackNode = node;
            this.items.push(item);
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

    removeWidget = vi.fn((element: HTMLElement): FakeGridStack => {
        this.items = this.items.filter((item) => item !== element);
        delete (element as GridItemHTMLElement).gridstackNode;
        return this;
    });

    batchUpdate = vi.fn((flag = true): FakeGridStack => {
        this.batching = flag;
        if (!flag && this.dirty) this.fireChange();
        return this;
    });

    destroy = vi.fn((): FakeGridStack => this);

    getGridItems(): GridItemHTMLElement[] {
        return [...this.items];
    }

    getColumn(): number {
        return this.columns;
    }

    getRow(): number {
        return Math.max(
            0,
            ...this.items.map(
                (item) =>
                    (item.gridstackNode?.y ?? 0) + (item.gridstackNode?.h ?? 1),
            ),
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

    /** Spec helper: what a breakpoint does, without firing `change`. */
    setColumns(columns: number): void {
        this.columns = columns;
    }

    /** Spec helper: fires an event with every node, as a drag or a resize ends. */
    trigger(name: string): void {
        const nodes = this.items.map((item) => item.gridstackNode!);
        for (const handler of this.handlers.get(name) ?? []) {
            handler(new Event(name), nodes);
        }
    }

    private changed(): void {
        if (this.batching) {
            this.dirty = true;
        } else {
            this.fireChange();
        }
    }

    private fireChange(): void {
        this.dirty = false;
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
