/**
 * Reader-side views: ways of looking at a spectrum that is already correct.
 *
 * These live here, in the frontend, and never in a `RendererConfig`. That is the
 * invariant written in `manuspectrum/constants/xy_presets.py`: a configuration
 * stores what turns a file's columns into the physical quantity its technique
 * measures, and nothing beyond it. A derivative or a pseudo-absorbance is not
 * that — it is a lens, and which lens you want depends on the question you are
 * asking, so it belongs to whoever is reading, not to a row every analysis of
 * that technique shares.
 *
 * Three rules the control must keep:
 *
 *   - the base quantity is always the default. A remembered or curator-chosen
 *     default would read as "the official view" and stop the reader looking
 *     further;
 *   - nothing is silent. The chosen view is named in the axis label and in the
 *     caption under the chart, so a transformed curve can never pass for the
 *     instrument's output;
 *   - a view composes strictly AFTER the configuration. The config produces the
 *     quantity; the view is a way of reading it. Applying log10(1/R) to raw
 *     counts would be meaningless.
 *
 * Palettes are per instrument family, because most transforms are nonsense
 * outside their own: Kubelka-Munk models diffuse reflectance and has no meaning
 * applied to an XRF count spectrum.
 *
 * Deliberately absent: smoothing, and derivatives outside FORS. Savitzky-Golay
 * needs a window matched to the instrument's spectral resolution — nine points
 * suits a spectrum sampled every cm-1 and destroys peaks in one sampled every
 * 0.1 cm-1. Offering a fixed window to a reader who did not set up the
 * acquisition invites a wrong reading. Baseline correction, the operation Raman
 * actually needs, is not implemented in the engine at all.
 */

import {
    TRANSFORM_KUBELKA_MUNK,
    TRANSFORM_LOG_INVERSE_R,
    TRANSFORM_NORMALIZE_AREA,
    TRANSFORM_NORMALIZE_MAX,
    TRANSFORM_DERIVATIVE,
} from 'utils/xy-transforms';

//: The view every palette opens on: the quantity the configuration produced.
export const BASE_VIEW = 'base';

const view = (key, transforms) => ({ key, transforms });

const NORMALISE_MAX = view('normalize-max', [{ type: TRANSFORM_NORMALIZE_MAX }]);
const NORMALISE_AREA = view('normalize-area', [
    { type: TRANSFORM_NORMALIZE_AREA },
]);
const PSEUDO_ABSORBANCE = view('log-inverse-r', [
    { type: TRANSFORM_LOG_INVERSE_R },
]);
const KUBELKA_MUNK = view('kubelka-munk', [{ type: TRANSFORM_KUBELKA_MUNK }]);

// Savitzky-Golay over nine points, second-order polynomial — the usual starting
// point, and stated in the caption so the reader knows what produced the curve.
const derivative = (order) =>
    view(`derivative-${order}`, [
        { type: TRANSFORM_DERIVATIVE, order: order, window: 9, polyOrder: 2 },
    ]);

export const VIEWS_BY_PRESET = {
    // Reflectance spectroscopy. Pseudo-absorbance and derivatives are protocol
    // here rather than garnish: for dye identification, first-derivative
    // features are more reliable markers than raw reflectance minima, because
    // absorption band positions shift with the substrate.
    fors: [PSEUDO_ABSORBANCE, KUBELKA_MUNK, derivative(1), derivative(2)],
    colorimetry: [PSEUDO_ABSORBANCE, KUBELKA_MUNK],

    // Reflection-mode infrared holds a reflectance, so it gets the reflectance
    // lenses. log(1/R) is what the field actually reports for external
    // reflection; Kubelka-Munk is offered because diffuse reflection shares
    // this preset, and refused as a default because it models a diluted
    // powder that non-invasive measurement never is.
    ftir_reflection: [PSEUDO_ABSORBANCE, KUBELKA_MUNK, NORMALISE_MAX],

    // Counts against energy or angle: the only meaningful lens from the current
    // primitives is putting two spectra on the same scale to compare them.
    xrf: [NORMALISE_MAX],
    xrd: [NORMALISE_MAX],
    raman: [NORMALISE_MAX],
    ftir: [NORMALISE_MAX],
    uv_vis: [NORMALISE_MAX],
    luminescence: [NORMALISE_MAX],

    // Mass spectra: intensity is arbitrary, so normalising to the total ion
    // current is what makes two acquisitions comparable at all.
    mass_spec: [NORMALISE_AREA, NORMALISE_MAX],

    // Total-emission normalisation counters shot-to-shot laser energy drift.
    libs: [NORMALISE_AREA],
};

/**
 * The views on offer for a configuration, base first.
 *
 * A configuration with no preset key — one a curator built by hand — gets the
 * base view alone. Defining named views is a separate feature; guessing which
 * lenses suit an unknown file would be worse than offering none.
 */
export const viewsFor = (config) => {
    const palette = VIEWS_BY_PRESET[config?.presetKey] || [];
    return [view(BASE_VIEW, []), ...palette];
};

/** Look a view up by key, falling back to the base rather than throwing. */
export const findView = (config, key) =>
    viewsFor(config).find((candidate) => candidate.key === key) ||
    view(BASE_VIEW, []);

export default { VIEWS_BY_PRESET, viewsFor, findView, BASE_VIEW };
