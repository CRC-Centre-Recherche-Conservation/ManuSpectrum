"""The Frollo TAPAC thesaurus and the controlled lists drawn from it.

Pure data, like the other constants modules: no Django import.

The "Thesaurus des Techniques d'analyses et d'examens (TAPAC)" is published on
the Frollo Opentheso instance as thesaurus ``th12`` (``pkg/NOTICE``, 1.5). Its
concepts are addressed by their Opentheso id (``idc``) and the thesaurus id
(``idt``): ``https://frollo.notre-dame.science/opentheso/?idc=61296&idt=th12``
is the page of "fiber optic reflectance spectrometry" (FORS).
"""

#: Opentheso id of the TAPAC thesaurus on Frollo.
FROLLO_THESAURUS_ID = "th12"

#: Address of a TAPAC concept, from its Opentheso concept id.
FROLLO_CONCEPT_URL = (
    "https://frollo.notre-dame.science/opentheso/?idc={concept_id}&idt="
    + FROLLO_THESAURUS_ID
)

#: Controlled lists whose items are TAPAC concepts (both from th12, see
#: ``pkg/NOTICE``). The ids are those of the package's ConceptSchemes.
FROLLO_LIST_IDS = (
    # "Frollo - Analysis and examination techniques (TAPAC)"
    "12dc9a7b-b177-450a-a927-711fa7882882",
    # "Frollo - Sample Taking Technique"
    "78080ed9-d78e-4d88-8df6-66f69e63e509",
)


def frollo_concept_url(concept_id):
    """The Frollo address of the TAPAC concept whose Opentheso id is *concept_id*."""
    return FROLLO_CONCEPT_URL.format(concept_id=concept_id)
