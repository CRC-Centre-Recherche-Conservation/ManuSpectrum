/**
 * Colours the MapLibre style paints with. WebGL takes resolved colours, not
 * custom properties, so they are read once from the tokens of
 * `_ms-chrome.scss`; `FALLBACK_COLOURS` holds the same values (a spec pins
 * them equal) for a page whose stylesheet has not loaded.
 */
export interface MapColours {
    sea: string;
    land: string;
    coast: string;
    ink: string;
    /** The names of the historical polities (`--ink-muted`). */
    inkMuted: string;
    /** Rings, dashed rings and historical borders (`--series-context`). */
    ring: string;
    surface: string;
    /** The selected place (`--blue-text`). */
    blue: string;
    /** The territory hatch lines (`--bg`). */
    paper: string;
    /** The digit drawn on a firm pip (`--focus-on`). */
    focusOn: string;
    /** The hue of each followed slot (index 0 is slot 1). */
    focus: readonly [string, string, string, string];
}

export const COLOUR_TOKENS: Readonly<
    Record<Exclude<keyof MapColours, "focus">, string>
> = {
    sea: "--map-sea",
    land: "--map-land",
    coast: "--map-coast",
    ink: "--ink",
    inkMuted: "--ink-muted",
    ring: "--series-context",
    surface: "--surface",
    blue: "--blue-text",
    paper: "--bg",
    focusOn: "--focus-on",
};

export const FOCUS_TOKENS = [
    "--focus-1",
    "--focus-2",
    "--focus-3",
    "--focus-4",
] as const;

export const FALLBACK_COLOURS: MapColours = {
    sea: "#e4ebf1",
    land: "#f4f0e7",
    coast: "#b7c4cf",
    ink: "#1a1a2e",
    inkMuted: "#4a4a5e",
    ring: "#8a8999",
    surface: "#ffffff",
    blue: "#1d4ed8",
    paper: "#faf9f7",
    focusOn: "#ffffff",
    focus: ["#3d2e8d", "#1e6256", "#93499e", "#760a03"],
};

/** The map colours under `element`; a token that is unset or empty takes its fallback. */
export function readColours(element: Element): MapColours {
    const computed = getComputedStyle(element);
    const token = (name: string, fallback: string): string =>
        computed.getPropertyValue(name).trim() || fallback;
    const colours = { ...FALLBACK_COLOURS };
    for (const [key, name] of Object.entries(COLOUR_TOKENS) as [
        keyof typeof COLOUR_TOKENS,
        string,
    ][]) {
        colours[key] = token(name, FALLBACK_COLOURS[key]);
    }
    colours.focus = [
        token(FOCUS_TOKENS[0], FALLBACK_COLOURS.focus[0]),
        token(FOCUS_TOKENS[1], FALLBACK_COLOURS.focus[1]),
        token(FOCUS_TOKENS[2], FALLBACK_COLOURS.focus[2]),
        token(FOCUS_TOKENS[3], FALLBACK_COLOURS.focus[3]),
    ];
    return colours;
}
