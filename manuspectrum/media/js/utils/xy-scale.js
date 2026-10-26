/**
 * Axis scale of an XY chart: linear or logarithmic Y.
 *
 * A logarithmic Y is a way of drawing the axis, never a treatment of the data:
 * the stored values, the configuration and the transforms of `xy-transforms.js`
 * are untouched, and a hover still reads the real value. Pure functions, no
 * page and no Plotly import, so the Arches report reader and the Explorer
 * workshop share one rule and a spec runs without a bundle.
 *
 * Plotly (`type: 'log'`) drops every point whose value is not strictly
 * positive, which cuts a line wherever a count is zero. `logScaleFigure`
 * therefore lays such a point on the smallest positive value of its own curve
 * and keeps the real value in `customdata` for the hover.
 */

export const SCALE_LINEAR = "linear";
export const SCALE_LOG = "log";

const isPositive = (value) =>
    typeof value === "number" && Number.isFinite(value) && value > 0;

// A trace on the secondary (right) axis keeps its own linear scale.
const onPrimaryAxis = (trace) => !trace?.yaxis || trace.yaxis === "y";

/** The smallest strictly positive value of an array, or null when none. */
export const smallestPositive = (values) => {
    let smallest = null;
    for (const value of values || []) {
        if (isPositive(value) && (smallest === null || value < smallest)) {
            smallest = value;
        }
    }
    return smallest;
};

/**
 * Whether a logarithmic Y can show these traces: every curve on the primary
 * axis needs at least one positive value, and there must be one such curve.
 */
export const canUseLogScale = (traces) => {
    const curves = (traces || []).filter(onPrimaryAxis);
    return (
        curves.length > 0 &&
        curves.every((trace) => smallestPositive(trace.y) !== null)
    );
};

/** An annotation's Y on a log axis, which Plotly reads as log10; null if not positive. */
export const annotationLogY = (y) => (isPositive(y) ? Math.log10(y) : null);

const HOVER_TEMPLATE = "%{x}, %{customdata}<extra>%{fullData.name}</extra>";

/**
 * What Plotly needs to draw `traces` on a logarithmic Y axis.
 *
 * Returns `{ traces, yaxis }`: copies of the traces whose non-positive values
 * are replaced by the curve's smallest positive value (the real values go to
 * `customdata`, shown by `hovertemplate`), and the `yaxis` layout fragment
 * (`{ type: 'log' }`). Input traces are not mutated. A curve with no positive
 * value is returned unchanged; callers gate on `canUseLogScale`.
 */
export const logScaleFigure = (traces) => ({
    traces: (traces || []).map((trace) => {
        if (!onPrimaryAxis(trace)) return trace;
        const floor = smallestPositive(trace.y);
        if (floor === null) return trace;
        const real = Array.from(trace.y);
        return {
            ...trace,
            y: real.map((value) => (isPositive(value) ? value : floor)),
            customdata: real,
            hovertemplate: HOVER_TEMPLATE,
        };
    }),
    yaxis: { type: SCALE_LOG },
});

export default {
    SCALE_LINEAR,
    SCALE_LOG,
    smallestPositive,
    canUseLogScale,
    annotationLogY,
    logScaleFigure,
};
