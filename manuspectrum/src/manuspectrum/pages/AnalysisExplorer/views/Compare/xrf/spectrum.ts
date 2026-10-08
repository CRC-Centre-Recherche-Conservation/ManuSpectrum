/** Peak search and line presence on a raw spectrum (energies in keV). Pure. */

export type Series = ArrayLike<number>;

export interface NetSignal {
    net: number;
    sigma: number;
    present: boolean;
}

export interface Peak {
    index: number;
    x: number;
    y: number;
    prominence: number;
}

const PRESENT_SIGMAS = 3;
const COUNT_TOLERANCE = 1e-6;

/** Mean spacing of the abscissa, always positive; 0 for fewer than 2 points. */
export function channelWidth(x: Series): number {
    if (x.length < 2) {
        return 0;
    }
    return Math.abs(x[x.length - 1] - x[0]) / (x.length - 1);
}

/** Index of the point closest to `value`; works on ascending or descending x. */
export function nearestIndex(x: Series, value: number): number {
    const n = x.length;
    if (n === 0) {
        return -1;
    }
    const ascending = x[n - 1] >= x[0];
    let low = 0;
    let high = n - 1;
    while (high - low > 1) {
        const mid = (low + high) >> 1;
        if (x[mid] < value === ascending) {
            low = mid;
        } else {
            high = mid;
        }
    }
    return Math.abs(x[low] - value) <= Math.abs(x[high] - value) ? low : high;
}

/** Inclusive index range of the points whose x lies in [from, to]. */
function indexRange(
    x: Series,
    from: number,
    to: number,
): [number, number] | null {
    const n = x.length;
    if (n === 0) {
        return null;
    }
    let a = nearestIndex(x, Math.min(from, to));
    let b = nearestIndex(x, Math.max(from, to));
    if (a > b) {
        [a, b] = [b, a];
    }
    const low = Math.min(from, to);
    const high = Math.max(from, to);
    while (a <= b && (x[a] < low || x[a] > high)) {
        a += 1;
    }
    while (b >= a && (x[b] < low || x[b] > high)) {
        b -= 1;
    }
    return a <= b ? [a, b] : null;
}

/** Index of the maximum of y within `halfWidth` of x, or the nearest index. */
export function snapToPeak(
    x: Series,
    y: Series,
    value: number,
    halfWidth: number,
): number {
    const range = indexRange(x, value - halfWidth, value + halfWidth);
    if (range === null) {
        return nearestIndex(x, value);
    }
    let best = range[0];
    for (let i = range[0] + 1; i <= range[1]; i += 1) {
        if (y[i] > y[best]) {
            best = i;
        }
    }
    return best;
}

const countLike = new WeakMap<object, boolean>();

function looksLikeCounts(y: Series): boolean {
    const cached = countLike.get(y);
    if (cached !== undefined) {
        return cached;
    }
    let result = y.length > 0;
    for (let i = 0; i < y.length && result; i += 1) {
        const value = y[i];
        if (
            value < 0 ||
            Math.abs(value - Math.round(value)) > COUNT_TOLERANCE
        ) {
            result = false;
        }
    }
    countLike.set(y, result);
    return result;
}

function windowValues(
    x: Series,
    y: Series,
    centre: number,
    width: number,
): number[] {
    const range = indexRange(x, centre - width / 2, centre + width / 2);
    if (range === null) {
        return [];
    }
    const values: number[] = [];
    for (let i = range[0]; i <= range[1]; i += 1) {
        values.push(y[i]);
    }
    return values;
}

function median(values: number[]): number {
    const sorted = [...values].sort((a, b) => a - b);
    const mid = sorted.length >> 1;
    return sorted.length % 2 === 1
        ? sorted[mid]
        : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Pooled deviation about each window's own mean, so a slope adds nothing. */
function pooledDeviation(windows: number[][]): number {
    let sum = 0;
    let degrees = 0;
    for (const values of windows) {
        if (values.length < 2) {
            continue;
        }
        const mean = values.reduce((total, v) => total + v, 0) / values.length;
        sum += values.reduce((total, v) => total + (v - mean) ** 2, 0);
        degrees += values.length - 1;
    }
    return degrees > 0 ? Math.sqrt(sum / degrees) : 0;
}

/**
 * Net signal of a line at `energy`: the maximum of y within ±fwhm/2 minus a
 * linear background between the medians of two windows of width `fwhm`
 * centred at energy ± 1.5·fwhm (one window alone gives a flat background; when
 * the two medians differ by more than 3σ, one window sits on a neighbouring
 * peak and the lower one is taken).
 * Count-like series (all ≥ 0, integers) take σ = √max(background, 1); other
 * series the deviation within the background windows (about each window's mean). Present when
 * net > 3σ.
 */
export function netSignal(
    x: Series,
    y: Series,
    energy: number,
    fwhm: number,
): NetSignal {
    const peak = snapToPeak(x, y, energy, fwhm / 2);
    const top = peak >= 0 ? y[peak] : 0;
    const left = windowValues(x, y, energy - 1.5 * fwhm, fwhm);
    const right = windowValues(x, y, energy + 1.5 * fwhm, fwhm);
    if (left.length === 0 && right.length === 0) {
        return { net: top, sigma: 0, present: false };
    }
    let background: number;
    if (left.length === 0) {
        background = median(right);
    } else if (right.length === 0) {
        background = median(left);
    } else {
        const low = Math.min(median(left), median(right));
        const high = Math.max(median(left), median(right));
        const spread = looksLikeCounts(y)
            ? Math.sqrt(Math.max(low, 1))
            : pooledDeviation([left, right]);
        // A window sitting on a neighbouring peak would hide the line.
        background =
            high - low > PRESENT_SIGMAS * spread ? low : (low + high) / 2;
    }
    const sigma = looksLikeCounts(y)
        ? Math.sqrt(Math.max(background, 1))
        : pooledDeviation([left, right]);
    const net = top - background;
    return { net, sigma, present: net > PRESENT_SIGMAS * sigma };
}

/** Sliding extreme over indices [i - radius, i + radius], clipped, in O(n). */
function slidingExtreme(
    y: Series,
    radius: number,
    better: (a: number, b: number) => boolean,
): Float64Array {
    const n = y.length;
    const out = new Float64Array(n);
    const deque = new Int32Array(n);
    let head = 0;
    let tail = 0;
    let next = 0;
    for (let i = 0; i < n; i += 1) {
        const reach = Math.min(n - 1, i + radius);
        while (next <= reach) {
            while (tail > head && !better(y[deque[tail - 1]], y[next])) {
                tail -= 1;
            }
            deque[tail] = next;
            tail += 1;
            next += 1;
        }
        while (deque[head] < i - radius) {
            head += 1;
        }
        out[i] = y[deque[head]];
    }
    return out;
}

const peakMemo = new WeakMap<object, WeakMap<object, Map<string, Peak[]>>>();

/**
 * The `k` strongest peaks of y, by prominence (height above the lowest point
 * within 2·fwhm either side), each a maximum within ±fwhm/2. Memoised per
 * (y, x, k, fwhm) so the same arguments return the same array.
 */
export function strongestPeaks(
    x: Series,
    y: Series,
    k: number,
    fwhm: number,
): Peak[] {
    let byX = peakMemo.get(y);
    if (byX === undefined) {
        byX = new WeakMap();
        peakMemo.set(y, byX);
    }
    let byArgs = byX.get(x);
    if (byArgs === undefined) {
        byArgs = new Map();
        byX.set(x, byArgs);
    }
    const key = `${k}|${fwhm}`;
    const hit = byArgs.get(key);
    if (hit !== undefined) {
        return hit;
    }
    const peaks = findPeaks(x, y, fwhm)
        .sort((a, b) => b.prominence - a.prominence || a.index - b.index)
        .slice(0, Math.max(0, k));
    byArgs.set(key, peaks);
    return peaks;
}

function findPeaks(x: Series, y: Series, fwhm: number): Peak[] {
    const width = channelWidth(x);
    if (y.length === 0 || width === 0) {
        return [];
    }
    const half = Math.max(1, Math.round(fwhm / 2 / width));
    const wide = Math.max(half + 1, Math.round((2 * fwhm) / width));
    const ceiling = slidingExtreme(y, half, (a, b) => a >= b);
    const floor = slidingExtreme(y, wide, (a, b) => a <= b);
    const peaks: Peak[] = [];
    let previous = -1;
    for (let i = 0; i < y.length; i += 1) {
        if (y[i] !== ceiling[i] || y[i] <= floor[i]) {
            continue;
        }
        // A flat top is one peak: keep its first point.
        if (previous >= 0 && i - previous <= half && y[previous] === y[i]) {
            continue;
        }
        previous = i;
        peaks.push({
            index: i,
            x: x[i],
            y: y[i],
            prominence: y[i] - floor[i],
        });
    }
    return peaks;
}
