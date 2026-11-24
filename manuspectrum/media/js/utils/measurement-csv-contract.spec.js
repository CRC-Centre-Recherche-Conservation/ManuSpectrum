/**
 * Vitest spec — the bare CSV contract the raw-instrument converters write,
 * drawn by the browser reader.
 *
 * `tests/fixtures/measurement_files/contract/cases.json` holds, per preset, a
 * copy of its stored configuration and the series `read_series` draws from the
 * synthetic CSV next to it; `tests/test_measurement_csv_contract.py` pins the
 * server side and regenerates the files (`MS_WRITE_CONTRACT=1`).
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

import { describe, expect, it } from "vitest";

import XyParser from "./xy-parser";
import {
    applyTransforms,
    expandStoredConfig,
    seriesRoles,
} from "./xy-transforms.js";

const CONTRACT = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../../../../tests/fixtures/measurement_files/contract",
);

const cases = JSON.parse(
    fs.readFileSync(path.join(CONTRACT, "cases.json"), "utf-8"),
);

/** The curve the reader draws on its left axis, finite points only. */
const drawn = (text, stored) => {
    const config = expandStoredConfig(stored);
    const parsed = applyTransforms(XyParser.parse(text, config), config);
    let values = parsed.y;
    if (parsed.ys) {
        const roles = seriesRoles(parsed, config);
        const index = parsed.ys.findIndex(
            (_, i) =>
                (roles[i] || "yLeft") !== "yRight" && roles[i] !== "ignore",
        );
        values = parsed.ys[index];
    }
    const points = parsed.x
        .map((x, i) => [x, values[i]])
        .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
    return {
        x: points.map((point) => point[0]),
        y: points.map((point) => point[1]),
        xReversed: Boolean(config?.display?.xReversed),
    };
};

describe("measurement CSV contract — the browser draws what the server draws", () => {
    it("covers every preset the converters feed", () => {
        expect(cases.map((c) => c.presetKey).sort()).toEqual([
            "fors",
            "ftir",
            "ftir_reflection",
            "mass_spec",
            "raman",
            "xrf",
            "xrf_channel",
        ]);
    });

    it.each(cases.map((c) => [c.presetKey, c]))(
        "draws %s as the server does",
        (_, c) => {
            const text = fs.readFileSync(path.join(CONTRACT, c.file), "utf-8");

            expect(XyParser.validateContent(text).valid).toBe(true);
            const curve = drawn(text, c.config);

            expect(curve.x).toHaveLength(c.expected.x.length);
            curve.x.forEach((x, i) =>
                expect(x).toBeCloseTo(c.expected.x[i], 9),
            );
            expect(curve.y).toHaveLength(c.expected.y.length);
            curve.y.forEach((y, i) =>
                expect(y).toBeCloseTo(c.expected.y[i], 9),
            );
            expect(curve.xReversed).toBe(c.expected.x_reversed);
        },
    );
});
