# Measurement file fixtures

Files here are public demo files under a free licence, or synthetic files built
by the tests. No file comes from a laboratory's own data. Each source is listed
with its origin and licence.

## Elio XRF text export (`elio_mca`)

Synthetic. Built in memory by `tests/measurement_fixtures.elio_mca`, with
invented header values; nothing is stored here. The copy at
`tests/fixtures/xy/elio_xrf.mca` is written by the same function.

## InDoRES — Mappa mundi d'Albi (`delimited`)

Dataset « Parchment, ink and colouring materials analyses of the Mappa mundi of
Albi », doi:10.48579/PRO/T2VBXF
(https://data.indores.fr/dataset.xhtml?persistentId=doi:10.48579/PRO/T2VBXF),
licence CC BY 4.0. Authors: Laurianne Robinet, Sylvie Heu-Thao, Giulia Galante,
Gaël Latour, Aurélie Tournié, Céline Daher, Anca Dan, Marie-Claire
Schanne-Klein, Anne Michelin, Jocelyne Deschaux.

- `indores_albi/F1_parchment.asd.txt`: a FORS reflectance spectrum exported as
  text (tab separator, decimal comma). Copied unmodified.
