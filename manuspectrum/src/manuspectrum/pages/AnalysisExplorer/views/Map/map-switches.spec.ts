// @vitest-environment node
//
// Reads the shared fixture from disk: jsdom's URL would not reach
// `fileURLToPath`, and nothing here touches the DOM.
import fs from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { matchingEvents } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/matching.ts";
import {
    withoutApproximate,
    withoutLevels,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/place-symbols.ts";

import type { MapEvent } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

interface SwitchCase {
    name: string;
    hideApproximate: boolean;
    hiddenLevels: string[];
    expected: { id: string; materials: string[] }[];
}

const FIXTURE: { events: unknown[]; cases: SwitchCase[] } = JSON.parse(
    fs.readFileSync(
        fileURLToPath(
            new URL(
                "../../../../../../../tests/fixtures/explorer/map-switches.json",
                import.meta.url,
            ),
        ),
        "utf-8",
    ),
);

function shown(events: MapEvent[], entry: SwitchCase): MapEvent[] {
    const dated = entry.hideApproximate ? withoutApproximate(events) : events;
    return matchingEvents(withoutLevels(dated, new Set(entry.hiddenLevels)));
}

describe("map display switches", () => {
    it.each(FIXTURE.cases.map((entry) => [entry.name, entry] as const))(
        "agree with the export: %s",
        (_name, entry) => {
            const events = FIXTURE.events as MapEvent[];
            expect(
                shown(events, entry).map((event) => ({
                    id: event.id,
                    materials: event.materials.map((material) => material.id),
                })),
            ).toEqual(entry.expected);
        },
    );
});
