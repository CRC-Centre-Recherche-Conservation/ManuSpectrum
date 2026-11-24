# Measurement file fixtures

Files here are public demo files under a free licence, or synthetic files built
by the tests. No file comes from a laboratory's own data. Each source is listed
with its origin and licence.

## Elio XRF text export (`elio_mca`)

Synthetic. Built in memory by `tests/measurement_fixtures.elio_mca`, with
invented header values; nothing is stored here. The copy at
`tests/fixtures/xy/elio_xrf.mca` is written by the same function.

## InDoRES — Mappa mundi d'Albi (`delimited`, `bruker_spx`, `galactic_spc`)

Dataset « Parchment, ink and colouring materials analyses of the Mappa mundi of
Albi », doi:10.48579/PRO/T2VBXF
(https://data.indores.fr/dataset.xhtml?persistentId=doi:10.48579/PRO/T2VBXF),
licence CC BY 4.0. Authors: Laurianne Robinet, Sylvie Heu-Thao, Giulia Galante,
Gaël Latour, Aurélie Tournié, Céline Daher, Anca Dan, Marie-Claire
Schanne-Klein, Anne Michelin, Jocelyne Deschaux.

- `indores_albi/F1_parchment.asd.txt`: a FORS reflectance spectrum exported as
  text (tab separator, decimal comma). Line endings normalised to LF; content
  otherwise unchanged.
- `indores_albi/X16_parchment.spx`: an XRF spectrum in Bruker's XML format
  (`bruker_spx`). Line endings normalised to LF; content otherwise unchanged.
- `indores_albi/Raman_Ms29f57v_s1_532_vert2.spc`: a Raman spectrum (532 nm) in
  Galactic SPC format (`galactic_spc`). Byte for byte unchanged.

## Expected values

`expected.json` holds values read with independent open libraries by
`oracle.py` (a documentation tool, never run by CI), keyed by fixture path.
