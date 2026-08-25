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
 *
 * A SECOND, independent axis governs where a transform may be *stored*. That
 * invariant is written in full in `manuspectrum/constants/xy_presets.py`: a stored
 * configuration may only hold **corrective** steps — those without which the
 * axis label would be false — while everything else is a **view**, composing
 * after the configuration, never the default, never silent.
 *
 * The two axes are meant to disagree. log(1/R) is parameter-free, so a preset
 * could apply it unaided, and still has no business being decided once for
 * every reader. Today only `reference-normalize` is corrective, so a stored
 * chain never exceeds one step.
 *
 * This module is the substrate for both sides and is deliberately unaware of
 * which one a caller is on: `expandStoredConfig` feeds it the corrective chain
 * today, and a reader-side control will feed it a view chain later, without
 * either needing a change here.
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

/**
 * Apparent absorbance, A = log10(1 / R). Undefined for R <= 0.
 *
 * PRECONDITION: R is a FRACTION in [0, 1], never a percentage. This is what
 * referenceNormalize produces — (S-D)/(W-D) — and what every preset naming
 * reflectance must therefore hold. Fed percentages the function does not fail,
 * it silently returns the wrong sign: at R = 50 the result is -1.70 where
 * +0.30 is meant. Nothing downstream can tell the two apart, which is why the
 * axis labels say "Reflectance (0-1)" rather than "(%)".
 */
export const logInverseR = (values) =>
    values.map((r) => (Number.isFinite(r) && r > EPSILON ? Math.log10(1 / r) : NaN));

/**
 * Kubelka-Munk remission, K/S = (1 - R)^2 / (2R). Undefined for R <= 0.
 *
 * PRECONDITION: R is a FRACTION in [0, 1], as for logInverseR above. At R = 50
 * (a percentage) this returns 24.0 where 0.25 is meant — two orders of
 * magnitude, on a curve that still looks like a spectrum.
 */
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
export const MULTI_Y_SEPARATE = 'separate';
export const MULTI_Y_MEAN = 'mean';
export const MULTI_Y_REFERENCE = 'reference-normalize';

/**
 * Expand a stored configuration into what the parser and the engine read.
 *
 * A configuration records ONE answer to "several Y columns remain — what do we
 * plot?". The parser still wants `transformation: 'mean'` and the engine still
 * wants a `transforms` chain, so the single stored choice fans out here rather
 * than the two being written down separately: set independently, they could
 * contradict each other silently.
 *
 * A configuration with no `multiYHandling` is left untouched — that is the
 * pre-migration shape, and a cached copy of it must keep rendering.
 */
export const expandStoredConfig = (config) => {
    const choice = config?.multiYHandling;
    if (!choice) return config;
    return {
        ...config,
        transformation: choice === MULTI_Y_MEAN ? 'mean' : undefined,
        transforms:
            choice === MULTI_Y_REFERENCE
                ? [{ type: TRANSFORM_REFERENCE_NORMALIZE }]
                : [],
    };
};

/**
 * How each transform is named on an axis, and whether it renames the quantity.
 *
 * `annotates` steps qualify the quantity without replacing it — the axis keeps
 * naming the measurement and gains a bracket saying how it is being shown, so
 * the reader never loses the reference point. `renames` steps produce a
 * different physical quantity altogether.
 */
export const TRANSFORM_LABELS = {
    [TRANSFORM_REFERENCE_NORMALIZE]: { annotates: null },
    [TRANSFORM_LOG_INVERSE_R]: { annotates: 'log10(1/R)' },
    [TRANSFORM_KUBELKA_MUNK]: { annotates: 'Kubelka-Munk' },
    [TRANSFORM_NORMALIZE_MAX]: { annotates: 'normalised to max' },
    [TRANSFORM_NORMALIZE_AREA]: { annotates: 'normalised to area' },
    [TRANSFORM_SMOOTH]: { annotates: 'smoothed' },
    [TRANSFORM_DERIVATIVE]: { annotates: 'derivative' },
};

const chainSteps = (config) => {
    const chain = config?.transforms;
    return Array.isArray(chain) ? chain : [];
};

const stepType = (step) => (typeof step === 'string' ? step : step?.type);

/**
 * The Y axis label, derived rather than typed.
 *
 * The base quantity is what the file holds once the configuration's corrective
 * chain has run — that is what the configuration is *for*. Anything applied on
 * top is appended in brackets, so "Reflectance (%)" becomes
 * "Reflectance (%) [log10(1/R)]" and never silently turns into something else.
 *
 * Deriving it is the whole point: the label used to be free text with nothing
 * tying it to the chain, so a curator could apply Kubelka-Munk and leave the
 * axis reading "Reflectance". A label a reader cannot trust is worse than no
 * label at all.
 */
/**
 * The X axis label, which must not name a quantity the file does not hold.
 *
 * When a file carries intensities only, the abscissa is the row position — the
 * channel — and nothing in the file says what physical quantity those channels
 * correspond to. A preset declaring "Energy (keV)" is then asserting something
 * it cannot know, on a chart that looks entirely normal. The generated label
 * wins, so the axis states what it really is.
 *
 * `generatedLabel` is passed in rather than looked up: this module stays free
 * of `arches`, so it can be imported by a spec without a page around it.
 */
export const deriveXAxisLabel = (storedLabel, config, generatedLabel) =>
    config?.xColumnMode === 'generate' ? generatedLabel : storedLabel || '';

export const deriveAxisLabel = (baseLabel, config) => {
    const base = baseLabel || '';
    const annotations = chainSteps(config)
        .map((step) => TRANSFORM_LABELS[stepType(step)]?.annotates)
        .filter(Boolean);
    if (annotations.length === 0) return base;
    return `${base} [${annotations.join(', ')}]`.trim();
};

/**
 * A one-line statement of what was applied, for the caption under a chart.
 *
 * Returns a description even when nothing ran: silence must not be
 * indistinguishable from "nothing applied" — the convention JCAMP-DX and mzML
 * both enforce by making the processing field mandatory.
 */
export const describeChain = (config) => {
    const steps = chainSteps(config)
        .map(stepType)
        .filter((type) => type && TRANSFORM_LABELS[type]);

    if (steps.length === 0) return null;
    return steps.join(' -> ');
};

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
    expandStoredConfig,
    deriveAxisLabel,
    describeChain,
    TRANSFORM_LABELS,
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
