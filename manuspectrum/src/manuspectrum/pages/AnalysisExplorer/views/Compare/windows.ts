import { firstStoredTitle } from "@/manuspectrum/pages/AnalysisExplorer/xy/axis-titles.ts";

import type {
    AnalysisHit,
    CharacterizationSummary,
    FileEntry,
    Item,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    BasketItem,
    ItemKey,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export type AutoWindowKind =
    | "xy"
    | "micro"
    | "characterizations"
    | "not-in-chart";

/** XY windows shown unfolded; the next ones open folded to their header. */
export const UNFOLDED_XY_WINDOWS = 3;

/** The group of readable spectra whose configuration states no axis title. */
const NO_AXIS_GROUP = "-";

export const MICRO_WINDOW_ID = "auto:micro";
export const MATERIALS_WINDOW_ID = "auto:characterizations";
export const NOT_IN_CHART_WINDOW_ID = "auto:not-in-chart";

/** A file of a Selection item, under its item's label (A1…). */
export interface FileLine {
    key: ItemKey;
    slot: number;
    analysis: AnalysisHit;
    file: FileEntry;
}

export interface MaterialRow {
    key: ItemKey;
    slot: number;
    characterization: CharacterizationSummary;
}

/**
 * Why an item is in no chart: a raw instrument file or another file is
 * downloaded, imaging layers are compared later, an analysis may hold nothing
 * to show, and an item may no longer be visible.
 */
export type NotInChartReason =
    | "raw-file"
    | "file"
    | "imaging"
    | "no-data"
    | "missing";

export interface NotInChartEntry {
    key: ItemKey;
    slot: number;
    reason: NotInChartReason;
    analysis: AnalysisHit | null;
    file: FileEntry | null;
}

interface WindowBase {
    /** Stable: the same content keeps the same id whatever else the Selection holds. */
    id: string;
    /** The Selection keys the window shows, in slot order. */
    keys: ItemKey[];
}

export interface XyWindow extends WindowBase {
    kind: "xy";
    axisKey: string | null;
    /** The first stored configuration name, in slot order. */
    configName: string | null;
    /** The first stored axis titles, in slot order. */
    xLabel: string | null;
    yLabel: string | null;
    folded: boolean;
    curves: FileLine[];
}

export interface MicroWindow extends WindowBase {
    kind: "micro";
    images: FileLine[];
}

export interface MaterialsWindow extends WindowBase {
    kind: "characterizations";
    rows: MaterialRow[];
}

export interface NotInChartWindow extends WindowBase {
    kind: "not-in-chart";
    entries: NotInChartEntry[];
}

/** A window arranged from the Selection. */
export type AutoWindow =
    | XyWindow
    | MicroWindow
    | MaterialsWindow
    | NotInChartWindow;

export function xyWindowId(axisKey: string | null): string {
    return `auto:xy:${axisKey ?? NO_AXIS_GROUP}`;
}

export function windowIdsOf(windows: readonly AutoWindow[]): string[] {
    return windows.map((window) => window.id);
}

function isReadableSpectrum(file: FileEntry): boolean {
    return file.dataKind === "xy" && file.role === "readable";
}

function withKey(keys: ItemKey[], key: ItemKey): void {
    if (!keys.includes(key)) keys.push(key);
}

/** What one file of an older one-file key (`af:`) is shown as. */
function fileReason(file: FileEntry): NotInChartReason {
    return file.role === "raw" ? "raw-file" : "file";
}

class Collector {
    readonly curves = new Map<string, FileLine[]>();
    readonly images: FileLine[] = [];
    readonly rows: MaterialRow[] = [];
    readonly entries: NotInChartEntry[] = [];

    addFile(line: FileLine): boolean {
        if (isReadableSpectrum(line.file)) {
            const id = xyWindowId(line.file.viewer.axisKey);
            this.curves.set(id, [...(this.curves.get(id) ?? []), line]);
            return true;
        }
        if (line.file.dataKind === "micro-imaging") {
            this.images.push(line);
            return true;
        }
        return false;
    }

    addEntry(
        { key, slot }: BasketItem,
        reason: NotInChartReason,
        analysis: AnalysisHit | null = null,
        file: FileEntry | null = null,
    ): void {
        this.entries.push({ key, slot, reason, analysis, file });
    }

    add(item: BasketItem, read: Item): void {
        const { key, slot } = item;
        if (read.kind === "characterization") {
            this.rows.push({
                key,
                slot,
                characterization: read.characterization,
            });
        } else if (read.kind === "imaging") {
            this.addEntry(item, "imaging", read.analysis, read.file);
        } else if (read.kind === "analysis-file") {
            const line = {
                key,
                slot,
                analysis: read.analysis,
                file: read.file,
            };
            if (!this.addFile(line)) {
                this.addEntry(
                    item,
                    fileReason(read.file),
                    read.analysis,
                    read.file,
                );
            }
        } else {
            let shown = false;
            for (const file of read.files) {
                shown =
                    this.addFile({
                        key,
                        slot,
                        analysis: read.analysis,
                        file,
                    }) || shown;
            }
            const imaging = read.files.find(
                (file) => file.dataKind === "chemical-imaging",
            );
            if (imaging) {
                this.addEntry(item, "imaging", read.analysis, imaging);
            } else if (!shown) {
                this.addEntry(item, "no-data", read.analysis);
            }
        }
    }

    windows(): AutoWindow[] {
        const windows: AutoWindow[] = [...this.curves].map(
            ([id, curves], index): XyWindow => ({
                id,
                kind: "xy",
                keys: curves.reduce<ItemKey[]>((keys, curve) => {
                    withKey(keys, curve.key);
                    return keys;
                }, []),
                axisKey: curves[0].file.viewer.axisKey,
                configName: firstStoredTitle(
                    curves.map((curve) => curve.file.viewer.configName),
                ),
                xLabel: firstStoredTitle(
                    curves.map((curve) => curve.file.viewer.xLabel),
                ),
                yLabel: firstStoredTitle(
                    curves.map((curve) => curve.file.viewer.yLabel),
                ),
                folded: index >= UNFOLDED_XY_WINDOWS,
                curves,
            }),
        );
        if (this.images.length > 0) {
            const keys: ItemKey[] = [];
            for (const image of this.images) withKey(keys, image.key);
            windows.push({
                id: MICRO_WINDOW_ID,
                kind: "micro",
                keys,
                images: this.images,
            });
        }
        if (this.rows.length > 0) {
            windows.push({
                id: MATERIALS_WINDOW_ID,
                kind: "characterizations",
                keys: this.rows.map((row) => row.key),
                rows: this.rows,
            });
        }
        if (this.entries.length > 0) {
            windows.push({
                id: NOT_IN_CHART_WINDOW_ID,
                kind: "not-in-chart",
                keys: this.entries.map((entry) => entry.key),
                entries: this.entries,
            });
        }
        return windows;
    }
}

/**
 * The windows arranged from the Selection: one XY window per axis group
 * (`FileEntry.viewer.axisKey`, every readable spectrum of an analysis in its
 * slot), the micro-images, the identified materials, and what no window
 * draws. Windows and their contents follow slot order; an XY window comes
 * where its first slot does. An item not read yet waits outside the
 * windows; a key the items API reports missing is listed as such. Older
 * one-file (`af:`) and one-layer (`im:`) keys are read into the same windows.
 */
export function autoWindows(
    basket: readonly BasketItem[],
    byKey: ReadonlyMap<string, Item>,
    missing: ReadonlySet<string>,
): AutoWindow[] {
    const collector = new Collector();
    for (const item of [...basket].sort((a, b) => a.slot - b.slot)) {
        const read = byKey.get(item.key);
        if (read) {
            collector.add(item, read);
        } else if (missing.has(item.key)) {
            collector.addEntry(item, "missing");
        }
    }
    return collector.windows();
}

function curveId(curve: FileLine): string {
    return `${curve.key}|${curve.slot}|${curve.file.id}`;
}

function curvesOf(windows: readonly AutoWindow[]): Map<string, FileLine[]> {
    return new Map(
        windows.flatMap((window) =>
            window.kind === "xy" ? [[window.id, window.curves]] : [],
        ),
    );
}

/**
 * `next`, each XY window holding the curves array of `previous` when its
 * curves are the same files in the same slots: a window whose spectra did
 * not change keeps its curves' identity, and its chart is not drawn again.
 */
export function keepUnchangedCurves(
    previous: readonly AutoWindow[],
    next: AutoWindow[],
): AutoWindow[] {
    const kept = curvesOf(previous);
    return next.map((window) => {
        const curves = window.kind === "xy" ? kept.get(window.id) : undefined;
        if (
            window.kind !== "xy" ||
            !curves ||
            curves.map(curveId).join("\n") !==
                window.curves.map(curveId).join("\n")
        ) {
            return window;
        }
        return { ...window, curves };
    });
}

/** The XY windows of `next` holding a spectrum (file in a slot) their namesake in `previous` did not hold. */
export function xyWindowsGaining(
    previous: readonly AutoWindow[],
    next: readonly AutoWindow[],
): string[] {
    const before = curvesOf(previous);
    return [...curvesOf(next)].flatMap(([id, curves]) => {
        const known = new Set((before.get(id) ?? []).map(curveId));
        return curves.some((curve) => !known.has(curveId(curve))) ? [id] : [];
    });
}
