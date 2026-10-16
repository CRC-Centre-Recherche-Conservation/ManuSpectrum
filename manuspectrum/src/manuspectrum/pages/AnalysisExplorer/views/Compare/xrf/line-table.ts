/** `[energy keV, relative intensity, initial level]`. */
export type XrfLine = [number, number, string];

export interface XrfElement {
    z: number;
    lines: Record<string, XrfLine>;
    edges: Record<string, number>;
}

export interface XrfLineTable {
    source: string;
    version: string;
    elements: Record<string, XrfElement>;
}

let loading: Promise<XrfLineTable> | null = null;

/**
 * The X-ray line table, loaded once from the async `xrf-lines` chunk (only an
 * XRF window asks for it).
 */
export function loadLineTable(): Promise<XrfLineTable> {
    loading ??= import(
        /* webpackChunkName: "xrf-lines" */ "./xray-lines.json"
    ).then((module) => (module.default ?? module) as unknown as XrfLineTable);
    return loading;
}

/** Element symbols of the table, by atomic number. */
export function allSymbols(table: XrfLineTable): string[] {
    return Object.entries(table.elements)
        .sort(([, a], [, b]) => a.z - b.z)
        .map(([symbol]) => symbol);
}
