"""Default XY visualisation presets, and the analysis-technique -> preset map.

This module is **pure data**: no Django imports, no settings access, so it can be
imported from ``settings.py``, from migrations and from tests alike.

Two things live here:

``XY_PRESETS``
    One entry per family of instruments that share an axis convention. The
    ``config`` payload is stored verbatim in a ``RendererConfig`` row, so its
    shape must match what ``media/js/utils/xy-parser.js`` and
    ``media/js/viewmodels/file-widget-xy.js`` read.

``TECHNIQUE_PRESETS``
    An explicit list-item-UUID -> preset-key map against the controlled list
    "Frollo - Analysis and examination techniques (TAPAC)". Deliberately
    explicit rather than inherited down the thesaurus tree: a technique that is
    not listed here simply gets no default, which is the safe outcome. When the
    thesaurus gains an item, add it here consciously.

Adding a technique means adding a line to ``TECHNIQUE_PRESETS``. Adding a whole
new instrument family means adding an entry to ``XY_PRESETS`` **with a fresh
``config_id``** and a migration that seeds it.

The invariant
-------------

**A** ``RendererConfig`` **stores exactly what turns a file's columns into the
physical quantity its technique measures** — parsing options, column roles, one
exclusive answer to the multi-Y question, and corrective steps drawn from
``CORRECTIVE_TRANSFORMS`` — **and the Y axis label is derived from it, never
typed independently.**

**Everything beyond that quantity is a view.** A view composes strictly *after*
the configuration, is never the default, is never silent — its chain appears on
every chart and export, an explicit "none" included — and never lives in a
``RendererConfig``.

The test is not "is this standard practice", it is *what does the operation
do*: does it bring the data to the quantity the technique measures, or does it
apply a model to data that is already correct? Reflectance IS the ratio of
measurement to white reference, so ``reference-normalize`` is corrective and an
axis reading "Reflectance" is false without it — unless the instrument reached
the ratio itself, which a preset states with ``y_precorrected`` rather than
leaving to inference. Note the unit: the ratio is a **fraction in [0, 1]**,
never a percentage, because ``log(1/R)`` and Kubelka-Munk both consume it and
both return nonsense from a percentage. A derivative, a smoothing,
log(1/R) — those are ways of *reading* a correct curve, and which one you want
depends on the question you are asking, so they belong to the reader.

Why this is the last structural change to this configuration
------------------------------------------------------------

Every future need lands in one of two registries, and **neither changes the
config's shape**:

* a new **view**, in the view layer — a reader-side control, deferred until
  someone asks to see log(1/R) or a derivative in a report. Its acceptance
  criteria are already fixed: never the default, never silent, composed after
  the configuration, offered per technique;
* a new **corrective** entry in ``CORRECTIVE_TRANSFORMS`` — decided per
  technique, with the reasoning written next to it. E-RIHS's curation policy
  says each method must find its own level of processing, so this set is global
  only until a technique needs otherwise. Known candidates: TIC normalisation
  for MALDI (its intensity is arbitrary), background subtraction for XRD,
  cosmic-ray removal for Raman. None is needed by any technique in this
  database today.

Two further things are deliberately deferred, each with its trigger: a named,
stored *view* as a derived entity with its own identifier — the FORS
first-derivative protocol for dye identification is the expected first case,
since the literature finds derivative features more reliable than raw
reflectance minima — and an explicit ``base_level`` field with full PROV
export, which the named-view feature will need anyway.

Note that ``CORRECTIVE_TRANSFORMS`` and ``AUTO_SAFE_TRANSFORMS`` are different
axes and are *meant* to disagree. The first answers "what may be frozen into a
shared configuration?", the second "what may a preset apply by itself?".
log(1/R) is parameter-free, so a preset could apply it unaided — and still has
no business being decided once for every reader. A test asserts they stay
distinct; if they ever coincide, one of them has lost its meaning.
"""

from functools import lru_cache
import logging
import uuid

from django.conf import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_xy_renderer_info():
    """Loops through settings.RENDERERS to find 'xy-reader' and returns its ID and formats."""
    # We look for the renderer named 'xy-reader'
    for renderer in getattr(settings, "RENDERERS", []):
        if renderer.get("name") == "xy-reader":
            # Returning the ID and wrapping the extension in a list
            return renderer.get("id")

    # Default values if the renderer is not found in settings
    logger.warning("The 'xy-reader' renderer was not found in settings.RENDERERS")
    return None


XY_RENDERER_ID = get_xy_renderer_info()

# ---------------------------------------------------------------------------
# Analysis graph coordinates
# ---------------------------------------------------------------------------
# Both nodes below collect their own nodegroup, so node id == nodegroup id.
ANALYSIS_GRAPH_ID = "60c85aba-f079-45bc-997f-21cdd4f77b6d"

#: "Analysis technique used" — reference datatype, multiValue, cardinality 1.
TECHNIQUE_NODE_ID = "3bcb6798-7b55-11ef-ba46-5b6797b92ed6"
TECHNIQUE_NODEGROUP_ID = TECHNIQUE_NODE_ID

#: "Measurement Point data" — file-list datatype, cardinality n.
DATA_FILE_NODE_ID = "8fe5161a-7bf2-11ef-b1e5-dd514ecd97bc"
DATA_FILE_NODEGROUP_ID = DATA_FILE_NODE_ID

#: Controlled list backing ``TECHNIQUE_NODE_ID``
#: ("Frollo - Analysis and examination techniques (TAPAC)").
TECHNIQUE_LIST_ID = "12dc9a7b-b177-450a-a927-711fa7882882"


# ---------------------------------------------------------------------------
# Provenance of a file's renderer configuration
# ---------------------------------------------------------------------------
# Written alongside ``rendererConfig`` on each file entry so the mapping can
# tell its own work from a curator's. Once a curator has touched an entry, the
# mapping leaves it alone forever — including if they clear it.
CONFIG_SOURCE_KEY = "rendererConfigSource"
CONFIG_SOURCE_AUTO = "auto"
CONFIG_SOURCE_MANUAL = "manual"


# ---------------------------------------------------------------------------
# Column roles
# ---------------------------------------------------------------------------
# 'x', 'yLeft', 'yRight' and 'ignore' are the historical roles understood by the
# importer-configuration UI. 'reference' and 'dark' are additions that let a
# preset describe a reference-normalised acquisition declaratively, without the
# curator having to compute anything by hand.
ROLE_X = "x"
ROLE_Y_LEFT = "yLeft"
ROLE_Y_RIGHT = "yRight"
ROLE_IGNORE = "ignore"
ROLE_REFERENCE = "reference"  # white / blank reference channel
ROLE_DARK = "dark"  # dark current channel


# ---------------------------------------------------------------------------
# Transform primitives
# ---------------------------------------------------------------------------
# Only parameter-free, deterministic transforms may appear in a preset's default
# chain. Anything needing an analyst-chosen parameter (baseline anchors,
# smoothing window, derivative order) is offered in the UI but never applied
# silently: a researcher must be able to trust that what they see is the file,
# unless the chain visibly says otherwise.
TRANSFORM_REFERENCE_NORMALIZE = "reference-normalize"  # R = (S - D) / (W - D)
TRANSFORM_LOG_INVERSE_R = "log-inverse-r"  # A = log10(1 / R)
TRANSFORM_KUBELKA_MUNK = "kubelka-munk"  # K/S = (1 - R)^2 / (2R)
TRANSFORM_NORMALIZE_MAX = "normalize-max"  # y / max(y)
TRANSFORM_NORMALIZE_AREA = "normalize-area"  # y / sum(y), i.e. TIC
TRANSFORM_DERIVATIVE = "derivative"  # Savitzky-Golay n-th derivative
TRANSFORM_SMOOTH = "smooth"  # Savitzky-Golay smoothing
TRANSFORM_BASELINE = "baseline"  # baseline subtraction

#: Transforms safe to ship inside a preset: deterministic, no free parameter,
#: and a no-op when the columns they need are absent.
AUTO_SAFE_TRANSFORMS = frozenset(
    {
        TRANSFORM_REFERENCE_NORMALIZE,
        TRANSFORM_LOG_INVERSE_R,
        TRANSFORM_KUBELKA_MUNK,
        TRANSFORM_NORMALIZE_MAX,
        TRANSFORM_NORMALIZE_AREA,
    }
)

#: Transforms that need analyst-chosen parameters. Offered in the configuration
#: UI, never part of a default chain.
ANALYST_ONLY_TRANSFORMS = frozenset(
    {TRANSFORM_DERIVATIVE, TRANSFORM_SMOOTH, TRANSFORM_BASELINE}
)

#: Transforms a stored configuration may contain.
#:
#: A configuration describes what turns a file's columns into the physical
#: quantity its technique measures — nothing more. `reference-normalize` belongs
#: because reflectance IS the ratio of measurement to white reference: without
#: it the file holds raw counts, and an axis reading "Reflectance (%)" is simply
#: false. Everything else is a way of looking at data that is already correct,
#: and belongs to the reader, not to a row every analysis of that technique
#: shares.
#:
#: This is a DIFFERENT axis from AUTO_SAFE / ANALYST_ONLY above, and the two
#: deliberately disagree. That pair answers "what may a preset apply by itself?"
#: (parameter-free versus judgement-required). This one answers "what may be
#: frozen into a shared configuration?" A transform can be perfectly
#: deterministic — log10(1/R) is — and still have no business being decided once
#: for every reader.
#:
#: The boundary is technique-specific in principle: E-RIHS's curation policy
#: states each method must find its own level of processing. MALDI intensity is
#: arbitrary, so TIC normalisation there is arguably corrective; XRD background
#: subtraction straddles the line. None of those is needed by any technique in
#: this database today, so the set stays global until one is — and then it grows
#: here, per technique, with the reasoning written down.
CORRECTIVE_TRANSFORMS = frozenset({TRANSFORM_REFERENCE_NORMALIZE})


# ---------------------------------------------------------------------------
# What to plot when several Y columns remain
# ---------------------------------------------------------------------------
# One question with three mutually exclusive answers, replacing two independent
# settings that could both be set and, together, silently did nothing: `mean`
# collapses every Y column into one series at parse time, after which no column
# carries the `reference` role any more, so the normalisation found nothing to
# divide by and returned the data untouched.
#
# As an enum that state cannot be written down at all, which is a stronger
# guarantee than validating against it.
MULTI_Y_SEPARATE = "separate"  # plot every Y column as its own series
MULTI_Y_MEAN = "mean"  # average them into a single series
MULTI_Y_REFERENCE = "reference-normalize"  # R = (S - D) / (W - D)

MULTI_Y_CHOICES = frozenset({MULTI_Y_SEPARATE, MULTI_Y_MEAN, MULTI_Y_REFERENCE})


def _preset(config_id, name, description, x_label, y_label, **kwargs):
    """Build a preset entry, keeping the repeated scaffolding out of the table.

    Names and descriptions are English only. ``RendererConfig`` is a plain
    Django model with a ``TextField`` name — it has no i18n machinery — so a
    French label could only be stored *instead of* the English one, never
    alongside it. One language everyone in the lab reads beats a half-translated
    list.
    """
    display = {
        "chartTitle": kwargs.pop("chart_title", name),
        "xAxisLabel": x_label,
        "yAxisLabel": y_label,
        "xReversed": kwargs.pop("x_reversed", False),
    }
    config = {
        "display": display,
        "multiYHandling": kwargs.pop("multi_y", MULTI_Y_SEPARATE),
    }
    # The file already holds the quantity the Y label names, because the
    # instrument reached it before export. Without this, a preset naming a
    # quantity it does not compute is indistinguishable from one that forgot
    # to — which is what the axis-label test exists to catch. Setting it is a
    # claim about the instrument, so it is written next to the preset that
    # makes it, never assumed.
    if kwargs.pop("y_precorrected", False):
        config["yPrecorrected"] = True
    config.update(kwargs)
    return {
        "config_id": config_id,
        "name": name,
        "description": description,
        "config": config,
    }


#: Instrument families sharing an axis convention. Keys are stable identifiers
#: referenced by ``TECHNIQUE_PRESETS``; never rename one without a migration.
XY_PRESETS = {
    "xrf": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a01",
        "XRF — energy / counts",
        "Columns: 1 = energy (keV), 2 = counts. Peaks identify elements; the "
        "sloping background is the tube's bremsstrahlung and stays in place.",
        "Energy (keV)",
        "Counts",
    ),
    # The reversed wavenumber axis (4000 -> 400 cm-1) is the one near-universal
    # convention in vibrational spectroscopy; plotting FTIR ascending reads as
    # an error to any spectroscopist.
    # Infrared splits on ONE question — what quantity does the file hold? —
    # and the answer follows the sampling geometry, not the spectral region.
    #
    # Transmission and ATR both yield absorbance, so they share a preset and the
    # accessory is descriptive metadata, not a configuration. Reflection is the
    # break: an external-reflection or diffuse-reflection acquisition holds a
    # reflectance, and calling it absorbance inverts how every band reads.
    #
    # The two reflection geometries share one preset because they produce the
    # same chart. Splitting them would mean two rows identical to the character,
    # which is the redundancy `maldi` / `mass_spec` already demonstrates.
    "ftir": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a02",
        "FTIR — wavenumber (reversed) / absorbance",
        "Columns: 1 = wavenumber (cm-1), 2 = absorbance. Transmission and ATR. "
        "The axis runs right to left, as spectroscopists read it — the whole "
        "acquired range is shown. Convert %T to absorbance before upload.",
        "Wavenumber (cm⁻¹)",
        "Absorbance",
        x_reversed=True,
    ),
    # Reflection-mode infrared. The label names what the file holds; log(1/R)
    # and Kubelka-Munk are reader-side lenses, offered per technique in
    # media/js/utils/xy-views.js, never frozen into this row.
    #
    # Kubelka-Munk deliberately stays out of the label: it models a diluted,
    # optically thick powder, which non-invasive heritage measurement never is,
    # and the field reports log(1/R). Offering it as a view says "if you want
    # this model, ask for it"; naming it here would claim the file already is it.
    "ftir_reflection": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a0c",
        "FTIR reflection — wavenumber (reversed) / reflectance",
        "Columns: 1 = wavenumber (cm-1), 2 = reflectance (0-1, not %). External "
        "or diffuse reflection. Band shapes are derivative-like and are not "
        "directly comparable with transmission or ATR references.",
        "Wavenumber (cm⁻¹)",
        "Reflectance (0-1)",
        x_reversed=True,
        y_precorrected=True,
    ),
    # Raman shift is plotted ascending, unlike FTIR, even though both are cm-1.
    "raman": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a06",
        "Raman — shift / intensity",
        "Columns: 1 = Raman shift (cm-1), 2 = intensity. Ascending, unlike FTIR. "
        "Fluorescence background and cosmic spikes are the analyst's call.",
        "Raman shift (cm⁻¹)",
        "Intensity (a.u.)",
    ),
    # FORS exports frequently carry the target and the white reference as
    # separate columns (see tgt_count / ref_count in the ASD text export). When
    # the curator tags those columns, the normalisation runs; otherwise the
    # chain is a no-op and the raw counts are shown as-is.
    "fors": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a03",
        "FORS — wavelength / reflectance",
        "Columns: 1 = wavelength (nm), 2 = target, 3 = white reference, "
        "4 = dark (optional). Tag 3 and 4 under Column Assignment and the "
        "reflectance (S-D)/(W-D) is computed for you, as a fraction (0-1).",
        "Wavelength (nm)",
        "Reflectance (0-1)",
        multi_y=MULTI_Y_REFERENCE,
    ),
    # One preset for every mass spectrum. There used to be two — "MALDI-TOF"
    # and "Mass spectrometry" — carrying axis labels identical to the
    # character. They cost more than the duplication: an analysis tagged with
    # both a specific and a generic mass-spectrometry term made
    # config_id_for_techniques see two keys and return None, so the file got no
    # configuration at all. The guard is right to refuse a real disagreement;
    # here there was nothing to disagree about.
    #
    # Named for the measurement, not the instrument: the technique that carries
    # every analysis in this database is laser desorption, of which MALDI is one
    # variant, and titling every chart "MALDI-TOF" overstated what was known.
    "mass_spec": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a04",
        "Mass spectrometry — m/z / intensity",
        "Columns: 1 = m/z, 2 = intensity. Raw counts as acquired — baseline, "
        "smoothing and TIC normalisation stay analyst choices.",
        "m/z",
        "Intensity (a.u.)",
    ),
    "xrd": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a07",
        "XRD — 2θ / intensity",
        "Columns: 1 = 2-theta (degrees), 2 = counts. Ascending. Convert to "
        "d-spacing or Q downstream only: it makes the step non-uniform.",
        "2θ (°)",
        "Intensity (counts)",
    ),
    "uv_vis": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a08",
        "UV-Vis — wavelength / absorbance",
        "Columns: 1 = wavelength (nm), 2 = absorbance. Transmission geometry; "
        "use the FORS preset for reflectance.",
        "Wavelength (nm)",
        "Absorbance",
    ),
    "libs": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a09",
        "LIBS — wavelength / intensity",
        "Columns: 1 = wavelength (nm), 2 = intensity. Broadband 200-1000 nm, "
        "usually stitched from several spectrometer channels.",
        "Wavelength (nm)",
        "Intensity (counts)",
    ),
    "luminescence": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a0a",
        "Luminescence — wavelength / intensity",
        "Columns: 1 = emission wavelength (nm), 2 = intensity. Covers "
        "fluorescence, photo-, cathodo- and thermoluminescence.",
        "Wavelength (nm)",
        "Intensity (a.u.)",
    ),
    # A spectrocolorimeter calibrates against its own white tile before it
    # writes a file, so the export already holds the ratio — there is no
    # reference column to divide by, and the label is free-standing. That is a
    # claim about the instrument, hence `y_precorrected` rather than silence.
    # Revisit it the first time an export arrives carrying a white channel.
    "colorimetry": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a0b",
        "Colorimetry — wavelength / reflectance",
        "Columns: 1 = wavelength (nm), 2 = reflectance (0-1, not %). Already "
        "referenced by the instrument. The spectral curve behind CIE L*a*b* "
        "values.",
        "Wavelength (nm)",
        "Reflectance (0-1)",
        y_precorrected=True,
    ),
}


#: Controlled-list item UUID -> preset key, against the list
#: "Frollo - Analysis and examination techniques (TAPAC)"
#: (12dc9a7b-b177-450a-a927-711fa7882882). Comments carry the TAPAC concept URI
#: and the French preferred label so the table can be audited without a DB.
#:
#: Techniques absent from this map get no default config, on purpose.
#: Notably absent: chromatography (retention time), thermal analysis
#: (temperature), NMR and XPS (both conventionally reversed axes), EPR,
#: Mössbauer, EELS, impedance and voltammetry. They plot fine once a curator
#: configures them, but guessing their axes would do more harm than good.
# A generic term is mapped ONLY when every descendant it covers measures the
# same quantity. Three did not, and each handed a curator tagging the broad
# term a chart in the wrong unit with nothing on screen to say so:
#
#   61202 Fluorescence      [nm]  is the parent of  61209 Fluorescence X   [keV]
#   61237 Réflectométrie    [nm]  is the parent of  61238 … infrarouge     [cm-1]
#   61330 Spectrophotométrie[nm]  is the parent of  61332 … EDXRF          [keV]
#
# They are unmapped rather than re-pointed: no term above them is true for the
# whole subtree. The same holds inside the infrared family, where 61307 covers
# descendants in both measurement modes.
#
# The rule cannot be asserted by a unit test: it needs the thesaurus, which
# lives in the database and is never loaded into the test one. Check it by hand
# after editing this map — walk `ListItem.parent` for every key here and compare
# the axis labels of the presets a parent and a child land on.
TECHNIQUE_PRESETS = {
    # --- X-ray fluorescence and energy-dispersive X-ray spectrometry ---
    "d35a8f0a-4fdd-3733-abbe-3e13e3ba5d26": "xrf",  # 61209 — Fluorescence X
    "499a30a8-d3fe-3ea7-a49a-07d4755b216d": "xrf",  # 61210 — Fluorescence X à dispersion d'énergie
    "0c67412a-7b15-30cb-a15c-14e982cbd1fa": "xrf",  # 61211 — Fluorescence X à dispersion d'énergie semi portable
    "6d4ff657-5ac1-3a73-a8f9-06fe71e13cb0": "xrf",  # 61212 — Fluorescence X à dispersion de longueur d'onde
    "e05a5195-9f82-3453-9eb0-0d0d344d63ac": "xrf",  # 61213 — Fluorescence X en réflexion totale
    "cd7de52f-b6a7-3dce-9ccd-f6187fb79baa": "xrf",  # 61214 — Fluorescence X induite par particules accélérées
    "59367393-f619-3994-a359-b73e3d7e1184": "xrf",  # 61215 — Fluorescence X induite par rayonnement synchrotron
    "a2e4b31a-53fa-3d8c-8aa6-f5b8b2564629": "xrf",  # 61216 — Fluorescence X portable
    "9b85c40c-132d-3664-a869-e62fae06aa10": "xrf",  # 61217 — Microfluorescence x
    "add7b0da-e20d-3a94-a31c-6731c9a38f74": "xrf",  # 61243 — Spectrométrie à dispersion d'énergie
    "f3764e72-a135-3f9c-99c7-51f2bbfd56ae": "xrf",  # 61244 — Spectrométrie de rayon X à dispersion d'énergie
    "8e4f1cbf-e45c-3d99-a0fe-c87733550b7c": "xrf",  # 61304 — Spectrométrie ED XRDF
    "5de301f7-350a-33d8-8c9d-e9d5793b5c0c": "xrf",  # 61332 — Spectrophotométrie EDXRF
    "b8a8031e-4d30-3e6a-b538-c51fd4a20be7": "xrf",  # 61271 — Spectrométrie d'émission X induite par protons
    "71469e35-e876-3f58-8dd9-e84eb6151f3e": "xrf",  # 61272 — Spectrométrie d'émission X induite par protons PIA
    "5d54371f-d225-36fd-ab70-290d596b6f56": "xrf",  # 61273 — Spectrométrie d'émission X induite par protons PIH
    "a046f954-db78-3805-b107-9e8e20797fde": "xrf",  # 61058 — Microscopie confocale de fluorescence X
    "4059f249-d537-304f-a6b0-8cb2dab3e6a7": "xrf",  # 61064 — MEB associée à une microsonde à dispersion d'énergie
    "d53cd399-fb85-307f-8b66-02473d9d6013": "xrf",  # 61066 — MEB équipée d'un microanalyseur X à dispersion d'énergie
    # --- Infrared: absorbance (transmission / ATR) ---
    "f021c6c2-9b1c-3b14-b4d0-20e7be2e1c7d": "ftir",  # 61314 — Spectrométrie moyen infrarouge
    "86b42db2-bf11-3adf-98a3-8dcb12b493c3": "ftir",  # 61316 — SEIRA
    "8efe4d7b-5b84-344d-b514-0643d5ae1c5b": "ftir",  # 61251 — Spectrométrie d'absorption dans l'infrarouge
    "64ea26a1-99e3-3418-ad92-0725f96f20f4": "ftir",  # 61238 — Réflectométrie infrarouge
    # Unresolved acronym: no scope note, no English label, no attestation in
    # the literature. Left on the absorbance default rather than guessed at;
    # the thesaurus owner is the only route to certainty. Zero analyses use it.
    "7c7df6e4-e557-3607-88da-711fe3328504": "ftir",  # 61306 — Spectrométrie FTIIS
    # --- Infrared: reflection ---
    # 61308 IRTF is the generic Fourier-transform term, and it sits here rather
    # than under absorbance because of what this lab actually acquires: all 19
    # instrument files carry PLF='RFL' and ACC='30GradFocRefl'. A curator doing
    # ATR corrects it on their own files; the auto badge says the default was
    # deduced. Elsewhere the same term could well mean transmission.
    "3e8fbf96-68f4-3dc5-9e41-5d270940cddf": "ftir_reflection",  # 61308 — IRTF
    "44f1eded-7f04-31f4-a36a-adbd3ef38f80": "ftir_reflection",  # 61310 — réflexion diffuse
    "0855e4dc-795c-31e4-a050-d2101e0f1c06": "ftir_reflection",  # 61311 — absorption réflexion
    "e0a4fb46-d619-3f19-be79-c688e727e27e": "ftir_reflection",  # 61312 — … par modulation de polarisation
    "6c81f4fc-15a1-35fe-9082-cad955c18793": "ftir_reflection",  # 61313 — MicroIRRS
    # Deliberately unmapped, and why — an absence has to be a decision:
    #   61073 / 61233 / 61329  infrared microscopies. Run in transmission, ATR
    #       or reflection depending on the accessory, and the term says which
    #       none of the time. No default is safer than a guessed one.
    #   61315  near infrared. Ambiguous twice over: reported in cm-1 by FT
    #       instruments and in nm by dispersive ones, and dominated by diffuse
    #       reflectance in heritage work. This lab already reaches the region
    #       under IRTF (Alpha, to 6997 cm-1) and FORS (ASD, to 2500 nm).
    #   61307  the broad infrared term. The vocabulary proves it ambiguous
    #       rather than merely leaving it vague: its own descendants sit in
    #       both modes, so no single quantity is true for the subtree.
    #   61309  polarising FTIR. A child of IRTF that would have contradicted
    #       it, and nothing in the term settles which mode the polariser sits
    #       in front of.
    # --- Fibre-optic reflectance and diffuse reflectance ---
    "65ea330e-e7ef-3cee-8266-35dc71321421": "fors",  # 61296 — Spectrométrie de réflectance par fibre optique
    "f53d9c69-7dd3-3123-93c1-27ecc5af5cb3": "fors",  # 61331 — Spectrophotométrie d'absorption en réflexion diffuse
    # --- Mass spectrometry ---
    # The TAPAC list has no MALDI-TOF item; laser-desorption MS (61292) is the
    # nearest parent and is what the lab has been recording in practice.
    "5f9bfd47-9b4c-3b0c-a59c-7012504a06ed": "mass_spec",  # 61292 — Spectrométrie de masse par désorption laser
    "5ff53d67-a8b1-3aba-b059-c9f300663c39": "mass_spec",  # 61276 — Spectrométrie de masse
    # --- Raman ---
    "7f82d1b9-d04c-3aed-90d1-49f47eb41abb": "raman",  # 61320 — Spectrométrie Raman
    "912673fa-641e-3e20-8e79-053c1bb0232f": "raman",  # 61321 — Spectrométrie Raman à transformée de Fourier
    "72e9c5d5-f5ad-3de0-b7f9-a50d0ed79fb8": "raman",  # 61322 — Spectrométrie SERS
    "5d71b3f1-bce9-3f80-9324-10bf7c02c21b": "raman",  # 61078 — Microscopie Raman
    "97f01696-a583-3f0d-a2f1-be8e091bc8a4": "raman",  # 61234 — Microspectrométrie Raman
    "2dfba4b2-8d06-326b-8d03-6ab6d3d09480": "raman",  # 61235 — Microspectrométrie Raman laser
    # --- Diffraction ---
    "2956a3e1-cff8-3f4c-97c2-61a5483cae11": "xrd",  # 61193 — Diffraction X
    "d8c2422e-0028-39e3-a69b-dcb393f6bf5b": "xrd",  # 61194 — Diffraction X induite par rayonnement synchrotron
    "54ca065b-6dec-336c-9b1d-3cf88785d9c4": "xrd",  # 61195 — Diffraction WAXD
    "647c09e8-26ab-3925-adea-ea85e28e76d3": "xrd",  # 61196 — Diffraction X aux petits angles
    "312f531f-3ec2-3f7b-b9df-d15dac09fd76": "xrd",  # 61197 — Diffraction X par chambre Debye-Scherrer
    "4fdd066c-0d62-3058-9ce6-484789d1f110": "xrd",  # 61198 — Diffraction X par chambre Gandolfi
    "3d7b9297-364d-3019-8fc9-1bc3c2bd2618": "xrd",  # 61199 — Diffraction X par goniomètre
    "24f0bed4-70a6-3462-af4a-9aac0df7f0c9": "xrd",  # 61200 — Diffractométrie sur poudre
    "19d1dc99-ee66-3b46-bcb8-01d668465847": "xrd",  # 61201 — Microdiffraction X
    # --- UV-visible absorption ---
    "1bff6942-ad66-3d8b-bb0f-efef73cbe248": "uv_vis",  # 61252 — Absorption dans l'ultraviolet et le visible
    "2953a858-4ed5-365b-84fe-aa682464a577": "uv_vis",  # 61325 — Spectrométrie UV visible
    "104f3d14-f0fa-3d92-938f-8d512b44d12b": "uv_vis",  # 61323 — Spectrométrie UV
    "1b9a1258-78b9-3e4f-bab4-08aef803ffc5": "uv_vis",  # 61326 — Spectrométrie visible
    # --- LIBS ---
    "ac0efba0-ca21-3c9d-82f7-24dde26d9c53": "libs",  # 61247 — Spectrométrie de plasma induit par laser
    "49dfead4-68a5-3d78-bc1c-180f77022d14": "libs",  # 61248 — Idem, à résolution temporelle
    # --- Fluorescence and luminescence emission ---
    "5dc93f3e-c811-39da-9748-ceb574d7bb40": "luminescence",  # 61203 — Fluorescence 3D
    "0dcec4bf-202b-3498-824f-cd0917453764": "luminescence",  # 61204 — Fluorescence induite par laser
    "25c15fbb-87cb-3d37-8d0c-6ed5245963d6": "luminescence",  # 61205 — Fluorescence UV
    "f84f1a71-acc4-390c-8f49-7efd9c71bbf9": "luminescence",  # 61206 — Fluorescence UV VIS
    "cd5d7e30-d904-3503-a1f4-3c52b86a2642": "luminescence",  # 61207 — Fluorescence visible
    "07e3df54-ac1c-3fb5-a24f-349b8cd49096": "luminescence",  # 61208 — Fluorescence UV VIS
    "9535ef43-dd71-329b-8f8c-75fe8e862efa": "luminescence",  # 61218 — Fluorimétrie
    "d9d04aee-6d8a-3850-af8d-9afe323dc19f": "luminescence",  # 61219 — Spectrofluorométrie
    "5ca353af-510a-30ea-92b8-525cece33096": "luminescence",  # 61220 — Immunofluorescence
    "39897506-55c9-3224-9c2e-26b42e0038bf": "luminescence",  # 61221 — Luminescence
    "a8adbf75-fb24-375a-8bb1-df13586def51": "luminescence",  # 61222 — Bioluminescence
    "9f62be52-524b-3c7d-8958-d7f0796bfdfe": "luminescence",  # 61223 — Candoluminescence
    "c62971ed-b55b-3c2d-83cf-5b200dc78a8a": "luminescence",  # 61224 — Cathodoluminescence
    "f261ee89-ab58-399c-af7c-269050f5f857": "luminescence",  # 61225 — Chimiluminescence
    "8563bb96-dc17-3ec3-b7d0-db32c9eed016": "luminescence",  # 61226 — Électroluminescence
    "4931a2f0-7377-3a99-81fb-8588820f7c57": "luminescence",  # 61227 — Luminescence stimulée optiquement
    "a4731361-8fb7-341d-ae29-c8e0c114e9bc": "luminescence",  # 61228 — Photoluminescence
    "5d0ff190-2b33-3995-9523-9ec0838ad1b0": "luminescence",  # 61229 — Radioluminescence
    "80104c72-1428-3005-9bdb-c2b826cf5e51": "luminescence",  # 61230 — Thermoluminescence
    "ada668a3-b036-39bc-ab96-f052deca97a3": "luminescence",  # 61231 — Triboluminescence
    # --- Colorimetry ---
    "48d3a300-705a-3264-93bb-a583f85e0b16": "colorimetry",  # 61184 — Colorimétrie
    "966226ac-7d75-3265-bec6-6b70691fc174": "colorimetry",  # 61185 — Spectrocolorimétrie
}


#: Config ids of the seeded presets. They are the shared baseline every
#: technique-derived configuration points at, so they are protected: never
#: deletable, and editable only by a superuser. Membership is derived from
#: XY_PRESETS rather than a database flag, so a new preset is protected the
#: moment it is added here — nothing to remember, nothing to migrate.
SEEDED_CONFIG_IDS = frozenset(preset["config_id"] for preset in XY_PRESETS.values())


def canonical_config_id(config_id):
    """The one spelling of an id, or None when it is not an id at all.

    Everything that identifies a configuration has to agree on what "the same
    id" means, and Django decides that for us: ``UUIDField`` funnels its input
    through ``uuid.UUID(hex=...)``, which is case-insensitive and forgives
    missing hyphens, surrounding braces and a ``urn:uuid:`` prefix. A guard
    comparing raw strings therefore accepted a narrower set than the row lookup
    it was guarding, and ``7A1C…`` skipped the protection while resolving the
    protected row.

    Returns None rather than raising: a malformed id is not a protected one,
    and rejecting it is the job of the lookup that follows.
    """
    try:
        return str(uuid.UUID(str(config_id)))
    except (AttributeError, TypeError, ValueError):
        return None


def is_seeded_preset(config_id):
    """True for a configuration seeded by migration, false for a curator's own."""
    return canonical_config_id(config_id) in SEEDED_CONFIG_IDS


# Each seeded configuration carries the key of the preset it came from. This is
# an identifier, not a transform: it lets the reader-side control offer the
# views that make sense for that instrument family without the configuration
# ever holding an interpretive step. The invariant holds — a config still stores
# only what reaches the measured quantity.
for _key, _preset_entry in XY_PRESETS.items():
    _preset_entry["config"]["presetKey"] = _key
del _key, _preset_entry


#: Config keys the editing panel has never heard of.
#:
#: ``saveConfigEdit`` in ``importer-configuration.js`` builds its payload from
#: its own observables — delimiter, column roles, display block, multi-Y choice.
#: Anything that is not a field on that form is simply absent from the request.
SEED_OWNED_CONFIG_KEYS = ("presetKey", "yPrecorrected")


def merge_seed_owned_keys(stored, incoming):
    """Carry the keys the panel cannot send; replace everything else.

    Saving used to assign the request body over the whole config. The first
    superuser edit of a seeded preset therefore dropped ``presetKey``, and the
    reader-side view control — which looks the palette up by that key — went
    silently empty for every file of that technique.

    Merging *everything* would be worse than the bug it fixes. The panel
    serialises a cleared field as ``undefined`` and JSON omits it, so a blanket
    merge would resurrect the old value: an axis could never be un-reversed, a
    range never emptied. Only the keys the panel does not own are carried over,
    which leaves clearing a field working exactly as before.
    """
    stored = stored or {}
    preserved = {key: stored[key] for key in SEED_OWNED_CONFIG_KEYS if key in stored}
    return {**incoming, **preserved}


def preset_for_technique(list_item_id):
    """Return the preset dict for a controlled-list item id, or ``None``."""
    key = TECHNIQUE_PRESETS.get(str(list_item_id))
    return XY_PRESETS.get(key) if key else None


def config_id_for_techniques(list_item_ids):
    """Resolve a set of technique ids to a single RendererConfig id.

    The technique node is ``multiValue``, so an analysis may legitimately carry
    several techniques. Returns the shared config id when every mapped
    technique agrees, and ``None`` when they disagree or when none is mapped —
    guessing between conflicting techniques would silently mislabel the axes.
    """
    keys = {
        TECHNIQUE_PRESETS[str(i)] for i in list_item_ids if str(i) in TECHNIQUE_PRESETS
    }
    if len(keys) != 1:
        return None
    return XY_PRESETS[keys.pop()]["config_id"]
