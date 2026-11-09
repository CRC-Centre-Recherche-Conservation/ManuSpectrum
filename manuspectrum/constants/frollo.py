"""The Frollo TAPAC thesaurus and the controlled lists drawn from it.

Pure data, like the other constants modules: no Django import.

The "Thesaurus des Techniques d'analyses et d'examens (TAPAC)" is published on
the Frollo Opentheso instance as thesaurus ``th12`` (``pkg/NOTICE``, 1.5). Each
concept has an Opentheso id (``idc``, the value the package's SKOS files carry
in ``dcterms:identifier``) and an ARK, which Opentheso publishes as the
concept's URI: "fiber optic reflectance spectrometry" (FORS) is ``idc`` 61296
and ``https://ark.notre-dame.science/ark:/35572/ndpnf4ww5qcbn0h5b67ctmt``. The
ARK resolver redirects to the concept's page, and the ARK is the persistent
identifier the RO-Crate export and the IIIF annotations should cite. ARKs are
not derived from the ``idc``: ``frollo_arks.FROLLO_ARKS`` lists them.
"""

from manuspectrum.constants.frollo_arks import FROLLO_ARKS

#: Opentheso id of the TAPAC thesaurus on Frollo.
FROLLO_THESAURUS_ID = "th12"

#: The ARK resolver: a concept's URI is this prefix followed by its ARK name.
FROLLO_ARK_RESOLVER = "https://ark.notre-dame.science/ark:/"

#: Controlled lists whose items are TAPAC concepts (both from th12, see
#: ``pkg/NOTICE``). The ids are those of the package's ConceptSchemes.
FROLLO_LIST_IDS = (
    # "Frollo - Analysis and examination techniques (TAPAC)"
    "12dc9a7b-b177-450a-a927-711fa7882882",
    # "Frollo - Sample Taking Technique"
    "78080ed9-d78e-4d88-8df6-66f69e63e509",
)


def frollo_concept_uri(concept_id):
    """The ARK URI of the TAPAC concept whose Opentheso id is *concept_id*.

    None when the id is not in ``FROLLO_ARKS`` (a concept the package does not
    carry): its URI cannot be derived and must be looked up on Frollo.
    """
    ark = FROLLO_ARKS.get(str(concept_id).strip())
    return FROLLO_ARK_RESOLVER + ark if ark else None
