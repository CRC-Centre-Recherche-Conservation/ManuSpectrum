/**
 * A stand-in for `maplibre-gl` in jsdom, which has no WebGL. Each `Map`
 * records what the component asks of it, fires `load` on a microtask, and
 * answers `queryRenderedFeatures` with `rendered`. Mock the module with
 * `vi.mock("maplibre-gl", async () => (await import("…/testing/maplibre.ts")).maplibreModule())`.
 */

export const SNAPSHOT_URL = "data:image/png;base64,AAAA";

type Handler = (event: Record<string, unknown>) => void;

interface Listener {
    type: string;
    layer: string | null;
    handler: Handler;
    once: boolean;
}

export interface RecordedLayer {
    layer: { id: string } & Record<string, unknown>;
    before: string | undefined;
}

export class FakeSource {
    data: unknown;
    setDataCalls: unknown[] = [];
    urls: string[] = [];

    constructor(readonly spec: Record<string, unknown>) {
        this.data = spec.data;
    }

    setData(data: unknown): this {
        this.data = data;
        this.setDataCalls.push(data);
        return this;
    }

    setUrl(url: string): this {
        this.urls.push(url);
        return this;
    }
}

export class FakeMap {
    static instances: FakeMap[] = [];
    /** The next constructions throw, as MapLibre does without WebGL. */
    static failing = false;

    sources = new Map<string, FakeSource>();
    layers: RecordedLayer[] = [];
    featureStates: [{ source: string; id: string }, Record<string, unknown>][] =
        [];
    removedStates: { source: string; id: string }[] = [];
    layoutCalls: [string, string, unknown][] = [];
    paintCalls: [string, string, unknown][] = [];
    filterCalls: [string, unknown][] = [];
    fitCalls: [unknown, Record<string, unknown> | undefined][] = [];
    jumpCalls: Record<string, unknown>[] = [];
    zoomCalls: [string, Record<string, unknown> | undefined][] = [];
    controls: unknown[] = [];
    images = new Map<string, unknown>();
    updatedImages: string[] = [];
    resizeCount = 0;
    removed = false;
    rendered: { properties: Record<string, unknown> }[] = [];
    canvas = { style: { cursor: "" }, toDataURL: (): string => SNAPSHOT_URL };
    private listeners: Listener[] = [];

    constructor(readonly options: Record<string, unknown>) {
        if (FakeMap.failing) throw new Error("Failed to initialize WebGL");
        FakeMap.instances.push(this);
        queueMicrotask(() => this.fire("load"));
    }

    static reset(): void {
        FakeMap.instances = [];
        FakeMap.failing = false;
    }

    static last(): FakeMap {
        const found = FakeMap.instances.at(-1);
        if (!found) throw new Error("no map was built");
        return found;
    }

    addSource(id: string, spec: Record<string, unknown>): this {
        this.sources.set(id, new FakeSource(spec));
        return this;
    }

    getSource(id: string): FakeSource | undefined {
        return this.sources.get(id);
    }

    addLayer(layer: RecordedLayer["layer"], before?: string): this {
        this.layers.push({ layer, before });
        return this;
    }

    getLayer(id: string): RecordedLayer["layer"] | undefined {
        return this.layers.find((entry) => entry.layer.id === id)?.layer;
    }

    setFeatureState(
        target: { source: string; id: string },
        state: Record<string, unknown>,
    ): void {
        this.featureStates.push([target, state]);
    }

    removeFeatureState(target: { source: string; id: string }): void {
        this.removedStates.push(target);
    }

    setLayoutProperty(layer: string, name: string, value: unknown): this {
        this.layoutCalls.push([layer, name, value]);
        return this;
    }

    setPaintProperty(layer: string, name: string, value: unknown): this {
        this.paintCalls.push([layer, name, value]);
        return this;
    }

    setFilter(layer: string, filter: unknown): this {
        this.filterCalls.push([layer, filter]);
        return this;
    }

    fitBounds(bounds: unknown, options?: Record<string, unknown>): this {
        this.fitCalls.push([bounds, options]);
        return this;
    }

    jumpTo(options: Record<string, unknown>): this {
        this.jumpCalls.push(options);
        return this;
    }

    zoomIn(options?: Record<string, unknown>): this {
        this.zoomCalls.push(["in", options]);
        return this;
    }

    zoomOut(options?: Record<string, unknown>): this {
        this.zoomCalls.push(["out", options]);
        return this;
    }

    getCenter(): { lng: number; lat: number } {
        return { lng: 2.5, lat: 47 };
    }

    getZoom(): number {
        return 4;
    }

    getBearing(): number {
        return 0;
    }

    getPitch(): number {
        return 0;
    }

    addControl(control: unknown): this {
        this.controls.push(control);
        return this;
    }

    addImage(name: string, image: unknown): this {
        this.images.set(name, image);
        return this;
    }

    hasImage(name: string): boolean {
        return this.images.has(name);
    }

    updateImage(name: string, image: unknown): this {
        this.images.set(name, image);
        this.updatedImages.push(name);
        return this;
    }

    queryRenderedFeatures(): { properties: Record<string, unknown> }[] {
        return this.rendered;
    }

    resize(): this {
        this.resizeCount += 1;
        return this;
    }

    remove(): void {
        this.removed = true;
    }

    getCanvas(): FakeMap["canvas"] {
        return this.canvas;
    }

    triggerRepaint(): void {
        queueMicrotask(() => this.fire("render"));
    }

    on(
        type: string,
        layerOrHandler: string | Handler,
        handler?: Handler,
    ): this {
        this.listen(type, layerOrHandler, handler, false);
        return this;
    }

    once(
        type: string,
        layerOrHandler: string | Handler,
        handler?: Handler,
    ): this {
        this.listen(type, layerOrHandler, handler, true);
        return this;
    }

    off(
        type: string,
        layerOrHandler: string | Handler,
        handler?: Handler,
    ): this {
        const fn =
            typeof layerOrHandler === "function" ? layerOrHandler : handler;
        this.listeners = this.listeners.filter(
            (listener) => listener.type !== type || listener.handler !== fn,
        );
        return this;
    }

    /** Calls the listeners of `type`: those bound to `layer`, and those bound to no layer. */
    fire(
        type: string,
        event: Record<string, unknown> = {},
        layer: string | null = null,
    ): void {
        const called = this.listeners.filter(
            (listener) =>
                listener.type === type &&
                (listener.layer === null || listener.layer === layer),
        );
        this.listeners = this.listeners.filter(
            (listener) => !(listener.once && called.includes(listener)),
        );
        for (const listener of called) listener.handler({ type, ...event });
    }

    listenerCount(type: string): number {
        return this.listeners.filter((listener) => listener.type === type)
            .length;
    }

    private listen(
        type: string,
        layerOrHandler: string | Handler,
        handler: Handler | undefined,
        once: boolean,
    ): void {
        if (typeof layerOrHandler === "function") {
            this.listeners.push({
                type,
                layer: null,
                handler: layerOrHandler,
                once,
            });
        } else if (handler) {
            this.listeners.push({ type, layer: layerOrHandler, handler, once });
        }
    }
}

export class FakeControl {
    constructor(readonly options: Record<string, unknown> = {}) {}
}

export function maplibreModule(): Record<string, unknown> {
    const module = {
        Map: FakeMap,
        AttributionControl: FakeControl,
        NavigationControl: FakeControl,
    };
    return { default: module, ...module };
}
