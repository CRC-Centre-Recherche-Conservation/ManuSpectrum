import { safeHref } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";

import type {
    Box,
    Quarter,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/registration.ts";

export const REGISTRATION_STORAGE_KEY = "ms-explorer-registration-v1";
export const REGISTRATION_LIMIT = 100;

const VERSION = 1;

/**
 * The box of an entry that holds only a capture: no laid box is that small
 * (`registration.ts` keeps every side at 8 or more).
 */
export const UNPLACED: Box = { x: 0, y: 0, w: 1, h: 1 };

export interface Capture {
    url: string;
    width: number;
    height: number;
    canvas: string;
    at: number;
}

export interface Registration {
    canvas: string;
    box: Box;
    quarter: Quarter;
    capture: Capture | null;
    touched: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finite(value: unknown): value is number {
    return typeof value === "number" && Number.isFinite(value);
}

function parseBox(value: unknown): Box | null {
    if (!isRecord(value)) return null;
    const { x, y, w, h } = value;
    if (!finite(x) || !finite(y) || !finite(w) || !finite(h)) return null;
    if (w <= 0 || h <= 0) return null;
    return { x, y, w, h };
}

function parseCapture(value: unknown): Capture | null {
    if (!isRecord(value)) return null;
    const { url, width, height, canvas, at } = value;
    if (typeof url !== "string" || !/^https?:/i.test(url.trim())) return null;
    if (safeHref(url) === null) return null;
    if (!finite(width) || !finite(height) || width <= 0 || height <= 0) {
        return null;
    }
    if (typeof canvas !== "string" || !finite(at)) return null;
    return { url, width, height, canvas, at };
}

function parseEntry(value: unknown): Registration | null {
    if (!isRecord(value)) return null;
    const { canvas, quarter, touched } = value;
    const box = parseBox(value.box);
    if (typeof canvas !== "string" || canvas === "" || box === null) {
        return null;
    }
    if (quarter !== 0 && quarter !== 1 && quarter !== 2 && quarter !== 3) {
        return null;
    }
    if (!finite(touched)) return null;
    return {
        canvas,
        box,
        quarter,
        capture: parseCapture(value.capture),
        touched,
    };
}

/** Reads the stored record; an entry that cannot be trusted is dropped alone. */
export function parseRegistrations(
    raw: string | null,
): Record<string, Registration> {
    if (raw === null) return {};
    let parsed: unknown;
    try {
        parsed = JSON.parse(raw);
    } catch {
        return {};
    }
    if (!isRecord(parsed) || parsed.version !== VERSION) return {};
    if (!isRecord(parsed.entries)) return {};
    const entries: Record<string, Registration> = {};
    for (const [id, value] of Object.entries(parsed.entries)) {
        const entry = parseEntry(value);
        if (entry !== null) entries[id] = entry;
    }
    return entries;
}

/** The `REGISTRATION_LIMIT` most recently touched entries. */
export function keepRecent(
    entries: Record<string, Registration>,
): Record<string, Registration> {
    return Object.fromEntries(
        Object.entries(entries)
            .sort(([, a], [, b]) => b.touched - a.touched)
            .slice(0, REGISTRATION_LIMIT),
    );
}

/** Writes the entries `keepRecent` keeps. */
export function serializeRegistrations(
    entries: Record<string, Registration>,
): string {
    return JSON.stringify({
        version: VERSION,
        entries: keepRecent(entries),
    });
}
