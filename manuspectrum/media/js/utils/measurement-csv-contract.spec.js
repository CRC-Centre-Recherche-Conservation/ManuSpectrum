/**
 * Vitest spec — the bare CSV contract the raw-instrument converters write,
 * drawn by the browser reader.
 *
 * `tests/fixtures/measurement_files/contract/cases.json` holds, per preset, a
 * copy of its stored configuration and the series `read_series` draws from the
 * synthetic CSV next to it; `tests/test_measurement_csv_contract.py` pins the
 * server side and regenerates the files (`MS_WRITE_CONTRACT=1`).
 *
 * `contract/refused/` holds one CSV per violation `check_csv` names. The
 * checker is the gate for a lone CSV and is stricter than the card: the card
 * refuses only what `validateContent` refuses (no header, markup, one column)
 * and draws everything else as it reads it, with gaps (NaN), a spurious point
 * or a line that goes back. The `REFUSED` table pins what the card does with
 * each file, for the options every preset passes.
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

const options = (stored) => {
    const config = expandStoredConfig(stored);
    return {
        xColumnMode: config.xColumnMode,
        xColumnIndex: config.xColumnIndex,
    };
};

/**
 * What the card does with a refused file: `refused` (validateContent says no),
 * else the points it parses (`parsed`), those with finite x and y (`finite`)
 * and whether x only goes up (`ascending`).
 */
const REFUSED = {
    "bom.csv": { parsed: 3, finite: 3, ascending: true },
    "comment_line.csv": { parsed: 3, finite: 3, ascending: true },
    "header_invalid__digit.csv": { parsed: 4, finite: 3, ascending: true },
    "header_invalid__formula.csv": { parsed: 3, finite: 3, ascending: true },
    "header_invalid__markup.csv": { refused: true },
    "no_header.csv": { refused: true },
    "non_finite.csv": { parsed: 3, finite: 2, ascending: true },
    "not_numeric.csv": { parsed: 3, finite: 2, ascending: true },
    "not_utf8.csv": { parsed: 3, finite: 2, ascending: true },
    "quoted.csv": { parsed: 3, finite: 3, ascending: true },
    "row_length.csv": { parsed: 3, finite: 2, ascending: true },
    "separator.csv": { parsed: 3, finite: 3, ascending: true },
    "too_few_columns.csv": { refused: true },
    "too_few_rows.csv": { parsed: 1, finite: 1, ascending: true },
    "x_not_ascending.csv": { parsed: 3, finite: 3, ascending: false },
};

const browserOutcome = (text, stored) => {
    const config = expandStoredConfig(stored);
    if (!XyParser.validateContent(text, options(stored)).valid) {
        return { refused: true };
    }
    const parsed = applyTransforms(XyParser.parse(text, config), config);
    const finite = parsed.x.filter(
        (x, i) => Number.isFinite(x) && Number.isFinite(parsed.y[i]),
    );
    return {
        parsed: parsed.x.length,
        finite: finite.length,
        ascending: finite.every((x, i) => i === 0 || x > finite[i - 1]),
    };
};

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

            expect(
                XyParser.validateContent(text, options(c.config)).valid,
            ).toBe(true);
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

    it("keeps a negative x and an exponent in the series it draws", () => {
        const xrf = cases.find((c) => c.presetKey === "xrf");
        const spec = cases.find((c) => c.presetKey === "mass_spec");

        expect(xrf.expected.x[0]).toBe(-1.2);
        expect(spec.expected.y[0]).toBe(1e-7);
    });

    describe("a refused file", () => {
        const files = fs
            .readdirSync(path.join(CONTRACT, "refused"))
            .filter((name) => name.endsWith(".csv"))
            .sort();

        it("is listed in the table, and only those", () => {
            expect(files).toEqual(Object.keys(REFUSED).sort());
        });

        it.each(files.map((name) => [name]))(
            "%s: the card does what the table says, for every preset",
            (name) => {
                const text = fs.readFileSync(
                    path.join(CONTRACT, "refused", name),
                    "utf-8",
                );

                for (const c of cases) {
                    expect(browserOutcome(text, c.config), c.presetKey).toEqual(
                        REFUSED[name],
                    );
                }
            },
        );

        it("line_ending: a CRLF text is drawn as the clean one", () => {
            const text = "x,y\r\n1,2\r\n2,3\r\n3,5\r\n";

            for (const c of cases) {
                expect(browserOutcome(text, c.config)).toEqual({
                    parsed: 3,
                    finite: 3,
                    ascending: true,
                });
            }
        });
    });
});
