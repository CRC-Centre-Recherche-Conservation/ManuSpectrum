# Measurement file fixtures

Files here are public demo files under a free licence, or synthetic files built
by the tests. No file comes from a laboratory's own data. Each source is listed
with its origin and licence.

## Elio XRF text export (`elio_mca`)

Synthetic. Built in memory by `tests/measurement_fixtures.elio_mca`, with
invented header values; nothing is stored here. The copy at
`tests/fixtures/xy/elio_xrf.mca` is written by the same function.

## InDoRES — Mappa mundi d'Albi (`delimited`, `bruker_spx`, `galactic_spc`, `opus`)

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
- `indores_albi/IR1_parchment.0`: an FTIR reflectance spectrum in Bruker OPUS
  binary format (`opus`). Byte for byte unchanged.
- `indores_albi/SERS_Ms29f57v_s1_785_01.spc.0`: a SERS spectrum in Bruker OPUS
  binary format whose result block is an unclassified « Spectrum » on a point
  axis: detected as `opus`, refused as `unsupported_variant`. Byte for byte
  unchanged.
- `indores_albi/Raman_Ms29f57v_s1_532_vert2.spc`: a Raman spectrum (532 nm) in
  Galactic SPC format (`galactic_spc`). Byte for byte unchanged.

## asdreader — soil.asd (`asd`)

Source: https://github.com/pierreroudier/asdreader (`inst/extdata/soil.asd`).
Licence GPL-3, as declared in the package `DESCRIPTION`. Author: Pierre Roudier.
A soil spectrum collected in New Zealand with an ASD FieldSpec 3, file version 8
(raw counts and white reference). Byte for byte unchanged.

## Expected values

`expected.json` holds values read with independent open libraries by
`oracle.py` (a documentation tool, never run by CI), keyed by fixture path.
