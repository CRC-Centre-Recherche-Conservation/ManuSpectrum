import type { EventType } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import {
    parseTrack,
    serializeTrack,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";

export type MapMode = "places" | "territories" | "multiples";
export type TerritoryColour = "each" | "dominant";
export type MultiplesAxis = "material" | "century";

export interface MapState {
    mode: MapMode;
    colour: TerritoryColour;
    /** Influence radius of Territories, whole kilometres. */
    radius: number;
    multiples: MultiplesAxis;
    /** Followed material uris by slot (index + 1); null is a hole. */
    track: (string | null)[];
    brush: [number, number] | null;
    /** The OpenHistoricalMap borders layer (`layers=borders`). */
    borders: boolean;
}

export const RADIUS_MIN_KM = 60;
export const RADIUS_MAX_KM = 400;
export const RADIUS_DEFAULT_KM = 150;

/** The event types the server keeps when the request names none. */
export const DEFAULT_EVENT_TYPES = [
    "production",
    "modification",
    "alteration",
] as const satisfies readonly EventType[];

const MODES: readonly MapMode[] = ["places", "territories", "multiples"];
const BORDERS = "borders";
const RANGE = /^(-?\d{1,4}),(-?\d{1,4})$/;
const WHOLE = /^\d{1,5}$/;

/** The types the reader sees ticked: `selected`, or the defaults when none is. */
export function shownEventTypes(selected: readonly EventType[]): EventType[] {
    return selected.length > 0 ? [...selected] : [...DEFAULT_EVENT_TYPES];
}

export function defaultMapState(): MapState {
    return {
        mode: "places",
        colour: "each",
        radius: RADIUS_DEFAULT_KM,
        multiples: "material",
        track: [],
        brush: null,
        borders: false,
    };
}

export function clampRadius(value: number): number {
    if (!Number.isFinite(value)) return RADIUS_DEFAULT_KM;
    return Math.min(RADIUS_MAX_KM, Math.max(RADIUS_MIN_KM, Math.round(value)));
}

export function mapStateFromQuery(query: URLSearchParams): MapState {
    const state = defaultMapState();
    state.mode = MODES.find((mode) => mode === query.get("mode")) ?? "places";
    state.colour = query.get("colour") === "dominant" ? "dominant" : "each";
    const radius = query.get("radius") ?? "";
    state.radius = WHOLE.test(radius)
        ? clampRadius(Number(radius))
        : RADIUS_DEFAULT_KM;
    state.multiples =
        query.get("multiples") === "century" ? "century" : "material";
    state.track = parseTrack(query.getAll("track"));
    const brush = RANGE.exec((query.get("brush") ?? "").trim());
    state.brush =
        brush && Number(brush[1]) <= Number(brush[2])
            ? [Number(brush[1]), Number(brush[2])]
            : null;
    state.borders = query
        .getAll("layers")
        .flatMap((raw) => raw.split(","))
        .includes(BORDERS);
    return state;
}

/** Sets on `query` the keys of `state` that differ from the default. */
export function writeMapState(state: MapState, query: URLSearchParams): void {
    const fallback = defaultMapState();
    if (state.mode !== fallback.mode) query.set("mode", state.mode);
    if (state.colour !== fallback.colour) query.set("colour", state.colour);
    if (state.radius !== fallback.radius)
        query.set("radius", String(state.radius));
    if (state.multiples !== fallback.multiples)
        query.set("multiples", state.multiples);
    if (state.track.length > 0) {
        for (const value of serializeTrack(state.track)) {
            query.append("track", value);
        }
    }
    if (state.brush) query.set("brush", `${state.brush[0]},${state.brush[1]}`);
    if (state.borders) query.set("layers", BORDERS);
}
