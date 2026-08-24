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
"""

from functools import lru_cache
import logging

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
    x_min = kwargs.pop("x_min", None)
    x_max = kwargs.pop("x_max", None)
    if x_min is not None:
        display["xRangeMin"] = x_min
    if x_max is not None:
        display["xRangeMax"] = x_max

    config = {"display": display, "transforms": kwargs.pop("transforms", [])}
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
    "ftir": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a02",
        "FTIR — wavenumber (reversed) / absorbance",
        "Columns: 1 = wavenumber (cm-1), 2 = absorbance. Plotted 4000 -> 400 as "
        "spectroscopists read it. Convert %T to absorbance before upload.",
        "Wavenumber (cm⁻¹)",
        "Absorbance",
        x_reversed=True,
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
        "reflectance (S-D)/(W-D) is computed for you.",
        "Wavelength (nm)",
        "Reflectance (%)",
        transforms=[{"type": TRANSFORM_REFERENCE_NORMALIZE}],
    ),
    "maldi": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a04",
        "MALDI-TOF — m/z / intensity",
        "Columns: 1 = m/z, 2 = intensity. Raw counts as acquired — baseline, "
        "smoothing and TIC normalisation stay analyst choices.",
        "m/z",
        "Intensity (a.u.)",
    ),
    "mass_spec": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a05",
        "Mass spectrometry — m/z / intensity",
        "Columns: 1 = m/z, 2 = intensity. Fallback for mass spectra with no "
        "dedicated preset.",
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
    "colorimetry": _preset(
        "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a0b",
        "Colorimetry — wavelength / reflectance",
        "Columns: 1 = wavelength (nm), 2 = reflectance (%). The spectral curve "
        "behind CIE L*a*b* values.",
        "Wavelength (nm)",
        "Reflectance (%)",
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
    # --- Infrared ---
    "2fe5191b-296f-31d1-aa37-0ecaa18eeeaf": "ftir",  # 61307 — Spectrométrie infrarouge
    "3e8fbf96-68f4-3dc5-9e41-5d270940cddf": "ftir",  # 61308 — IRTF
    "de75e16e-deb5-3eef-b342-2cf4818439f0": "ftir",  # 61309 — IRTF polarisante
    "44f1eded-7f04-31f4-a36a-adbd3ef38f80": "ftir",  # 61310 — Spectrométrie infrarouge à réflexion diffuse
    "0855e4dc-795c-31e4-a050-d2101e0f1c06": "ftir",  # 61311 — Spectrométrie infrarouge d'absorption réflexion
    "e0a4fb46-d619-3f19-be79-c688e727e27e": "ftir",  # 61312 — Idem, par modulation de polarisation
    "6c81f4fc-15a1-35fe-9082-cad955c18793": "ftir",  # 61313 — Spectrométrie MicroIRRS
    "f021c6c2-9b1c-3b14-b4d0-20e7be2e1c7d": "ftir",  # 61314 — Spectrométrie moyen infrarouge
    "6c8b9db7-709e-3631-bfc9-a8ad429247d9": "ftir",  # 61315 — Spectrométrie proche infrarouge
    "86b42db2-bf11-3adf-98a3-8dcb12b493c3": "ftir",  # 61316 — Spectrométrie SEIRA
    "0233ee87-52db-3db0-a85f-6a7c4b96bec7": "ftir",  # 61073 — Microscopie infrarouge
    "be00cd0a-0f8d-35f3-bce1-5c010e69a35f": "ftir",  # 61233 — Microspectrométrie infrarouge
    "a43b2c27-dbfa-3eeb-b940-e125c8abb919": "ftir",  # 61329 — Spectromicroscopie infrarouge
    "8efe4d7b-5b84-344d-b514-0643d5ae1c5b": "ftir",  # 61251 — Spectrométrie d'absorption dans l'infrarouge
    "64ea26a1-99e3-3418-ad92-0725f96f20f4": "ftir",  # 61238 — Réflectométrie infrarouge
    "7c7df6e4-e557-3607-88da-711fe3328504": "ftir",  # 61306 — Spectrométrie FTIIS
    # --- Fibre-optic reflectance and diffuse reflectance ---
    "65ea330e-e7ef-3cee-8266-35dc71321421": "fors",  # 61296 — Spectrométrie de réflectance par fibre optique
    "e1474f64-f7d8-36c3-88d3-9c3db7bf9573": "fors",  # 61237 — Réflectométrie
    "f53d9c69-7dd3-3123-93c1-27ecc5af5cb3": "fors",  # 61331 — Spectrophotométrie d'absorption en réflexion diffuse
    "24a9366e-69b3-3f9b-b526-469a19db8e93": "fors",  # 61330 — Spectrophotométrie
    # --- Mass spectrometry ---
    # The TAPAC list has no MALDI-TOF item; laser-desorption MS (61292) is the
    # nearest parent and is what the lab has been recording in practice.
    "5f9bfd47-9b4c-3b0c-a59c-7012504a06ed": "maldi",  # 61292 — Spectrométrie de masse par désorption laser
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
    "12ddaa76-d0e6-38f2-a34d-b566f979ad4b": "luminescence",  # 61202 — Fluorescence
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
