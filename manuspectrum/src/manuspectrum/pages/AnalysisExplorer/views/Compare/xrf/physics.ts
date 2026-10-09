import type { XrfElement, XrfLine } from "./line-table";

const MN_KA_KEV = 5.895;
const FANO = 0.114;
const PAIR_ENERGY_KEV = 0.00385;
const FWHM_FACTOR = 2.355;
const SI_ESCAPE_KEV = 1.74;
const SI_K_EDGE_KEV = 1.839;
const MIN_TOLERANCE_KEV = 0.1;
const ELECTRON_REST_KEV = 511;

const FOCUS_LINE_NAMES = ["Ka1", "Kb1", "La1", "Lb1", "Lg1", "Ma", "Mb"];
const PRINCIPAL_LINE_NAMES = ["Ka1", "La1", "Ma"];

const GREEK: Record<string, string> = {
    a: "α",
    b: "β",
    g: "γ",
    l: "ℓ",
    n: "ν",
    z: "ζ",
};

export interface LineRef {
    name: string;
    label: string;
    energy: number;
    intensity: number;
    initial: string;
}

/** Detector resolution (keV) at `energy`, from its FWHM at Mn Kα. */
export function fwhmAt(energy: number, fwhmMn: number): number {
    const statistics = (n: number) =>
        FWHM_FACTOR ** 2 * FANO * PAIR_ENERGY_KEV * n;
    const noise = Math.max(0, fwhmMn ** 2 - statistics(MN_KA_KEV));
    return Math.sqrt(noise + statistics(energy));
}

/** Half-width (keV) within which a peak is matched to a line. */
export function tolerance(energy: number, fwhmMn: number): number {
    return Math.max(MIN_TOLERANCE_KEV, fwhmAt(energy, fwhmMn) / 2);
}

/** Energy (keV) of `energy` after Compton scattering by `thetaDeg`. */
export function comptonEnergy(energy: number, thetaDeg: number): number {
    const cos = Math.cos((thetaDeg * Math.PI) / 180);
    return energy / (1 + (energy / ELECTRON_REST_KEV) * (1 - cos));
}

/** Si escape peak of `energy`, or null at or below the Si K edge. */
export function escapeOf(energy: number): number | null {
    return energy > SI_K_EDGE_KEV ? energy - SI_ESCAPE_KEV : null;
}

/** Whether the edge of the line's initial level lies below `kV` (unknown kV: yes). */
export function excitable(
    line: XrfLine,
    edges: Record<string, number>,
    kV: number | null,
): boolean {
    if (kV === null) {
        return true;
    }
    const edge = edges[line[2].split(",")[0]];
    return edge !== undefined && edge < kV;
}

/** `Ka1` → `Kα1`, `Lb2,15` → `Lβ2,15`. */
export function lineLabel(name: string): string {
    return (
        name.charAt(0) +
        (GREEK[name.charAt(1)] ?? name.charAt(1)) +
        name.slice(2)
    );
}

/** A table line as a `LineRef`. */
export function lineRef(name: string, line: XrfLine): LineRef {
    return {
        name,
        label: lineLabel(name),
        energy: line[0],
        intensity: line[1],
        initial: line[2],
    };
}

/** Lines used to confirm an element, those present in the table. */
export function focusLines(element: XrfElement): LineRef[] {
    return FOCUS_LINE_NAMES.filter((name) => name in element.lines).map(
        (name) => lineRef(name, element.lines[name]),
    );
}

/** The element's Kα1, else Lα1, else Mα, inside `range` and excitable. */
export function principalLine(
    element: XrfElement,
    range: [number, number],
    kV: number | null,
): LineRef | null {
    for (const name of PRINCIPAL_LINE_NAMES) {
        const line = element.lines[name];
        if (
            line &&
            line[0] >= range[0] &&
            line[0] <= range[1] &&
            excitable(line, element.edges, kV)
        ) {
            return lineRef(name, line);
        }
    }
    return null;
}
