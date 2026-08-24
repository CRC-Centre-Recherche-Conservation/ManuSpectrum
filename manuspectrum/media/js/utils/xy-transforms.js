/**
 * Display transformations for parsed XY spectra.
 *
 * These operate on the output of `xy-parser.parse()` and never touch the file:
 * what is stored stays the raw instrument export, and the chain applied to it
 * is recorded in the renderer configuration, so a reader can always tell what
 * they are looking at.
 *
 * Two families, deliberately kept apart:
 *
 *   - deterministic, parameter-free transforms (reference normalisation,
 *     log(1/R), Kubelka-Munk, max/area normalisation). A preset may apply these
 *     automatically, because their result is fully determined by the data and
 *     the column roles.
 *   - transforms that need an analyst's judgement (smoothing window, derivative
 *     order, baseline anchors). These are offered in the configuration UI but
 *     must never be part of a default chain — a silently smoothed spectrum is
 *     a misleading one.
 *
 * Column roles come from `config.display.columnAssignments`, so a FORS export
 * carrying `wavelength / tgt_count / ref_count` normalises itself once the
 * curator has tagged the reference column, with no arithmetic on their part.
 */

const EPSILON = 1e-12;

export const TRANSFORM_REFERENCE_NORMALIZE = 'reference-normalize';
export const TRANSFORM_LOG_INVERSE_R = 'log-inverse-r';
export const TRANSFORM_KUBELKA_MUNK = 'kubelka-munk';
export const TRANSFORM_NORMALIZE_MAX = 'normalize-max';
export const TRANSFORM_NORMALIZE_AREA = 'normalize-area';
export const TRANSFORM_SMOOTH = 'smooth';
export const TRANSFORM_DERIVATIVE = 'derivative';

export const ROLE_X = 'x';
export const ROLE_Y_LEFT = 'yLeft';
export const ROLE_Y_RIGHT = 'yRight';
export const ROLE_IGNORE = 'ignore';
export const ROLE_REFERENCE = 'reference';
export const ROLE_DARK = 'dark';

/** Transforms a preset may apply on its own. */
export const AUTO_SAFE_TRANSFORMS = [
    TRANSFORM_REFERENCE_NORMALIZE,
    TRANSFORM_LOG_INVERSE_R,
    TRANSFORM_KUBELKA_MUNK,
    TRANSFORM_NORMALIZE_MAX,
    TRANSFORM_NORMALIZE_AREA,
];

/** Transforms that require analyst-chosen parameters. */
export const ANALYST_ONLY_TRANSFORMS = [TRANSFORM_SMOOTH, TRANSFORM_DERIVATIVE];

/**
 * Maps a parser series index back to its column index in the file.
 *
 * The parser drops the X column from the Y list, so series `i` is file column
 * `i` when X was generated, and `i` or `i + 1` otherwise. This mirrors the
 * remap already performed in xy-reader.js and file-widget-xy.js.
 */
export const seriesColumnIndex = (seriesIndex, xColumnIndex, isGenerateMode) => {
    if (isGenerateMode) return seriesIndex;
    return seriesIndex < xColumnIndex ? seriesIndex : seriesIndex + 1;
};

/** Resolves the role of each parsed series from the column assignments. */
export const resolveRoles = (config, seriesCount) => {
    const display = config?.display || {};
    const assignments = display.columnAssignments;
    const isGenerate = config?.xColumnMode === 'generate';
    const xColumnIndex = parseInt(config?.xColumnIndex ?? 0, 10);

    const roles = new Array(seriesCount).fill(ROLE_Y_LEFT);
    if (!Array.isArray(assignments) || assignments.length === 0) return roles;

    const byColumn = new Map();
    assignments.forEach((assignment) => {
        byColumn.set(parseInt(assignment.columnIndex, 10), assignment.role);
    });

    for (let i = 0; i < seriesCount; i++) {
        const column = seriesColumnIndex(i, xColumnIndex, isGenerate);
        if (byColumn.has(column)) roles[i] = byColumn.get(column);
    }
    return roles;
};

/**
 * R = (S - D) / (W - D)
 *
 * Divides every measurement series by the white reference, subtracting the dark
 * current first when one is present. Returns the input untouched when no
 * reference column has been tagged — the normalisation is opt-in by design, so
 * an unconfigured file shows its raw counts rather than a silent ratio.
 */
export const referenceNormalize = (series, roles) => {
    const referenceIndex = roles.indexOf(ROLE_REFERENCE);
    if (referenceIndex === -1) return { series, roles };

    const reference = series[referenceIndex];
    const darkIndex = roles.indexOf(ROLE_DARK);
    const dark = darkIndex === -1 ? null : series[darkIndex];

    const outSeries = [];
    const outRoles = [];
    series.forEach((values, index) => {
        if (index === referenceIndex || index === darkIndex) return;
        outSeries.push(
            values.map((value, i) => {
                const d = dark ? dark[i] : 0;
                const denominator = reference[i] - d;
                if (!Number.isFinite(denominator) || Math.abs(denominator) < EPSILON) {
                    return NaN;
                }
                return (value - d) / denominator;
            })
        );
        outRoles.push(roles[index]);
    });

    // Every column was a reference or a dark: nothing left to plot, so keep the
    // original rather than hand back an empty chart.
    if (outSeries.length === 0) return { series, roles };
    return { series: outSeries, roles: outRoles };
};

/** Apparent absorbance, A = log10(1 / R). Undefined for R <= 0. */
export const logInverseR = (values) =>
    values.map((r) => (Number.isFinite(r) && r > EPSILON ? Math.log10(1 / r) : NaN));

/** Kubelka-Munk remission, K/S = (1 - R)^2 / (2R). Undefined for R <= 0. */
export const kubelkaMunk = (values) =>
    values.map((r) => {
        if (!Number.isFinite(r) || r <= EPSILON) return NaN;
        return ((1 - r) * (1 - r)) / (2 * r);
    });

/** Scales so the strongest point reads 1. */
export const normalizeMax = (values) => {
    const finite = values.filter(Number.isFinite);
    if (finite.length === 0) return values;
    const peak = Math.max(...finite.map(Math.abs));
    if (peak < EPSILON) return values;
    return values.map((v) => (Number.isFinite(v) ? v / peak : NaN));
};

/** Scales so the total signal sums to 1 (total ion current for mass spectra). */
export const normalizeArea = (values) => {
    const total = values.reduce(
        (sum, v) => (Number.isFinite(v) ? sum + Math.abs(v) : sum),
        0
    );
    if (total < EPSILON) return values;
    return values.map((v) => (Number.isFinite(v) ? v / total : NaN));
};

/**
 * Solves a small linear system by Gauss-Jordan elimination with partial
 * pivoting. Used only for the Savitzky-Golay normal equations, where the matrix
 * is a well-conditioned Vandermonde-Gram of order <= 6.
 */
const solve = (matrix, vector) => {
    const n = vector.length;
    const a = matrix.map((row, i) => [...row, vector[i]]);

    for (let col = 0; col < n; col++) {
        let pivot = col;
        for (let row = col + 1; row < n; row++) {
            if (Math.abs(a[row][col]) > Math.abs(a[pivot][col])) pivot = row;
        }
        if (Math.abs(a[pivot][col]) < EPSILON) return null;
        [a[col], a[pivot]] = [a[pivot], a[col]];

        const diagonal = a[col][col];
        for (let k = col; k <= n; k++) a[col][k] /= diagonal;

        for (let row = 0; row < n; row++) {
            if (row === col) continue;
            const factor = a[row][col];
            if (factor === 0) continue;
            for (let k = col; k <= n; k++) a[row][k] -= factor * a[col][k];
        }
    }
    return a.map((row) => row[n]);
};

/**
 * Savitzky-Golay convolution coefficients — the standard way to smooth or
 * differentiate a spectrum without the noise amplification a naive finite
 * difference produces.
 *
 * `at` is the position within the window where the fitted polynomial is
 * evaluated, in samples from its centre. It is 0 in the interior, and non-zero
 * near the edges, where the window can no longer be centred on the point of
 * interest (see savitzkyGolay). Duplicating edge samples instead would bias the
 * fit and is visibly wrong on a derivative.
 */
export const savitzkyGolayCoefficients = (
    windowSize,
    polyOrder,
    derivative,
    at = 0
) => {
    const half = Math.floor(windowSize / 2);
    const terms = polyOrder + 1;

    // Normal equations of the least-squares polynomial fit over the window.
    const gram = [];
    for (let i = 0; i < terms; i++) {
        gram.push([]);
        for (let j = 0; j < terms; j++) {
            let sum = 0;
            for (let z = -half; z <= half; z++) sum += Math.pow(z, i + j);
            gram[i].push(sum);
        }
    }

    // d-th derivative of t^k evaluated at `at`, i.e. k!/(k-d)! * at^(k-d).
    const derivativeOfTerm = (k) => {
        if (k < derivative) return 0;
        let factor = 1;
        for (let i = 0; i < derivative; i++) factor *= k - i;
        return factor * Math.pow(at, k - derivative);
    };

    const weights = [];
    for (let z = -half; z <= half; z++) {
        const rhs = [];
        for (let i = 0; i < terms; i++) rhs.push(Math.pow(z, i));
        const solution = solve(gram, rhs);
        if (!solution) return null;

        let weight = 0;
        for (let k = derivative; k < terms; k++) {
            weight += derivativeOfTerm(k) * solution[k];
        }
        weights.push(weight);
    }
    return weights;
};

/**
 * Applies a Savitzky-Golay filter. `derivative: 0` smooths; 1 and 2 give the
 * first and second derivative used to locate pigment inflection points in
 * reflectance spectra.
 *
 * Near the edges the window is held against the boundary and the polynomial is
 * evaluated off-centre, so a curve of order <= polyOrder is reproduced exactly
 * across the whole range rather than sagging at the ends.
 */
export const savitzkyGolay = (values, options = {}) => {
    const polyOrder = Math.max(0, parseInt(options.polyOrder ?? 2, 10));
    const derivative = Math.max(0, parseInt(options.derivative ?? 0, 10));

    let windowSize = parseInt(options.window ?? 9, 10);
    if (!Number.isFinite(windowSize) || windowSize < 3) windowSize = 3;
    if (windowSize % 2 === 0) windowSize += 1;
    if (windowSize > values.length) return values.map(() => NaN);
    if (polyOrder >= windowSize || derivative > polyOrder) return values;

    const half = Math.floor(windowSize / 2);
    const last = values.length - 1;
    const spacing =
        Number.isFinite(options.spacing) && Math.abs(options.spacing) > EPSILON
            ? options.spacing
            : 1;
    const scale = derivative === 0 ? 1 : 1 / Math.pow(spacing, derivative);

    // At most `windowSize` distinct evaluation offsets, so cache them.
    const cache = new Map();
    const weightsAt = (at) => {
        if (!cache.has(at)) {
            cache.set(
                at,
                savitzkyGolayCoefficients(windowSize, polyOrder, derivative, at)
            );
        }
        return cache.get(at);
    };

    return values.map((_, index) => {
        let start;
        let at;
        if (index < half) {
            start = 0;
            at = index - half;
        } else if (index > last - half) {
            start = values.length - windowSize;
            at = index - (last - half);
        } else {
            start = index - half;
            at = 0;
        }

        const weights = weightsAt(at);
        if (!weights) return NaN;

        let sum = 0;
        for (let j = 0; j < windowSize; j++) {
            const sample = values[start + j];
            if (!Number.isFinite(sample)) return NaN;
            sum += weights[j] * sample;
        }
        return sum * scale;
    });
};

/** Median spacing of the X axis, used to scale derivatives into real units. */
const medianSpacing = (x) => {
    if (!Array.isArray(x) || x.length < 2) return 1;
    const deltas = [];
    for (let i = 1; i < x.length; i++) {
        const delta = x[i] - x[i - 1];
        if (Number.isFinite(delta) && Math.abs(delta) > EPSILON) deltas.push(delta);
    }
    if (deltas.length === 0) return 1;
    deltas.sort((a, b) => a - b);
    return deltas[Math.floor(deltas.length / 2)];
};

const POINTWISE = {
    [TRANSFORM_LOG_INVERSE_R]: logInverseR,
    [TRANSFORM_KUBELKA_MUNK]: kubelkaMunk,
    [TRANSFORM_NORMALIZE_MAX]: normalizeMax,
    [TRANSFORM_NORMALIZE_AREA]: normalizeArea,
};

/**
 * Runs a configured chain over a parsed spectrum.
 *
 * Accepts and returns the two shapes xy-parser produces: `{x, y}` for a single
 * series and `{x, ys, seriesNames}` for several. Unknown transform names are
 * skipped rather than throwing, so a configuration written by a newer version
 * still renders on an older client.
 */
export const applyTransforms = (parsed, config) => {
    const chain = config?.transforms;
    if (!Array.isArray(chain) || chain.length === 0 || !parsed) return parsed;

    const isMulti = Array.isArray(parsed.ys);
    let series = isMulti ? parsed.ys.map((y) => [...y]) : [[...(parsed.y || [])]];
    let names = isMulti ? [...(parsed.seriesNames || [])] : null;
    let roles = resolveRoles(config, series.length);

    if (series.length === 0 || series[0].length === 0) return parsed;

    const spacing = medianSpacing(parsed.x);

    chain.forEach((step) => {
        const type = typeof step === 'string' ? step : step?.type;
        if (!type) return;

        if (type === TRANSFORM_REFERENCE_NORMALIZE) {
            const before = series.length;
            const result = referenceNormalize(series, roles);
            series = result.series;
            if (names && series.length !== before) {
                names = names.filter(
                    (_, i) => roles[i] !== ROLE_REFERENCE && roles[i] !== ROLE_DARK
                );
            }
            roles = result.roles;
            return;
        }

        if (type === TRANSFORM_SMOOTH || type === TRANSFORM_DERIVATIVE) {
            const options = {
                window: step?.window,
                polyOrder: step?.polyOrder,
                derivative: type === TRANSFORM_DERIVATIVE ? (step?.order ?? 1) : 0,
                spacing,
            };
            series = series.map((values) => savitzkyGolay(values, options));
            return;
        }

        const pointwise = POINTWISE[type];
        if (pointwise) series = series.map(pointwise);
    });

    if (isMulti) {
        return { ...parsed, ys: series, seriesNames: names || parsed.seriesNames };
    }
    return { ...parsed, y: series[0] };
};

export default {
    applyTransforms,
    resolveRoles,
    referenceNormalize,
    logInverseR,
    kubelkaMunk,
    normalizeMax,
    normalizeArea,
    savitzkyGolay,
    savitzkyGolayCoefficients,
    seriesColumnIndex,
    AUTO_SAFE_TRANSFORMS,
    ANALYST_ONLY_TRANSFORMS,
};
