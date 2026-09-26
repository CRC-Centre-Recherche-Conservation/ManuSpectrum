{% load i18n %}{% autoescape off %}# {{ title }}

{% blocktrans %}Data package exported from {{ site }} on {{ date }}.{% endblocktrans %}
{% for mark in marks %}
**{{ mark }}**
{% endfor %}
## {% trans "Contents" %}

- README.md: {% trans "this file." %}
- `data/<document>/<folio>/<analysis>/<file>`: {% trans "the data files, raw and readable, unchanged." %}
- metadata/analyses.csv, metadata/analyses.json: {% trans "one row per analysis: technique, object, zone, operators, dates, instrument, projects, measurement conditions, licences, dataset, permalink." %}
- metadata/characterizations.csv, metadata/characterizations.json: {% trans "one row per identified material: materials and certainty, colours, layers, elements by level, analyses cited in evidence, note." %}
- citations.bib, citations.ris, citations.json: {% trans "the citations in BibTeX, RIS and CSL-JSON." %}
{% if has_manifest %}- manifest.json: {% trans "the IIIF Presentation 3 manifest of the same scope." %}
{% endif %}- ro-crate-metadata.json: {% trans "the RO-Crate 1.2 description of the package, with the SHA-256 checksum of every file." %}
{% for note in notes %}
{{ note }}
{% endfor %}
## {% trans "How to cite" %}

{% for citation in citations %}- {{ citation }}
{% endfor %}
## {% trans "Data availability" %}

{{ availability }}
{% if datasets %}
{% trans "The data come from the datasets below; cite and reuse them by their identifier." %}

{% for dataset in datasets %}- {{ dataset.title }}: <{{ dataset.url }}>
{% endfor %}{% endif %}
## {% trans "Licences per file" %}

{% if files %}| {% trans "Path" %} | {% trans "Size (bytes)" %} | {% trans "Licence" %} | {% trans "Attribution" %} |
| --- | ---: | --- | --- |
{% for file in files %}| {{ file.path }} | {{ file.size }} | {{ file.licence }} | {{ file.attribution }} |
{% endfor %}{% else %}{% trans "No data file." %}
{% endif %}{% endautoescape %}
