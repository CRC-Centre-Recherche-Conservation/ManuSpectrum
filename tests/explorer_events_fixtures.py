"""The ServiceCase corpus with places, a modification, an alteration and dated carriers for the map's events.

Document « Ms 59 »: produced in Paris 1401–1500 (approximate). Its Component f. 1v is
produced in Lyon 1380–1395 (four bounds); f. 2r (« bare ») has no production. The
modification of f. 1v (1420–1430, approximate) took place at an abbey without a
geometry inside Normandie (a polygon) and cites the azurite. The alteration of the
document (1700–1800) took place in Lyon and names vermilion. Lead white (f. 1v)
falls to its Component's production, smalt (f. 2r) to the Document's. Analysis
« open » took place at the C2RMF (2024); Sample S1 (2023) at the hidden place.
Ms 300 has its own point, Ms 301 a derived copy and no date, Ms 302 no analysis.
"""

from arches.app.models.models import TileModel

from tests.test_explorer_service import ServiceCase

VERMILION = "http://vocab/vermilion"
LEAD_WHITE = "http://vocab/lead-white"
SMALT = "http://vocab/smalt"
HIGH = "http://vocab/highly-reliable"
LOW = "http://vocab/uncertain"
PARIS = (2.3488, 48.8534)
LYON = (4.8357, 45.764)
LAB = (2.3333, 48.8606)
OWN = (2.35, 48.86)
NORMANDIE = [
    [-1.9, 48.5],
    [-0.2, 48.4],
    [1.7, 49.0],
    [1.6, 49.9],
    [0.2, 49.75],
    [-1.95, 49.7],
    [-1.9, 48.5],
]


def collection(geometry, properties=None):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "f1",
                "type": "Feature",
                "geometry": geometry,
                "properties": properties or {},
            }
        ],
    }


def point(lng_lat):
    return {"type": "Point", "coordinates": list(lng_lat)}


class EventsCase(ServiceCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        new, tile, places = cls.new_resource, cls.tile, cls.places
        places["normandie"] = new("place", "Normandie")
        places["abbey"] = new("place", "Abbaye de Saint-Évroult")
        places["lab"] = new("place", "C2RMF")
        tile(places["paris"], "literal_location", collection(point(PARIS)))
        tile(
            places["paris"],
            "value_of_identifier",
            cls.string_value("https://www.geonames.org/2988507"),
        )
        tile(places["lyon"], "literal_location", collection(point(LYON)))
        tile(places["lab"], "literal_location", collection(point(LAB)))
        tile(
            places["normandie"],
            "literal_location",
            collection({"type": "Polygon", "coordinates": [NORMANDIE]}),
        )
        tile(places["normandie"], "part_of_places", cls.refs(places["france"]))
        tile(places["abbey"], "part_of_places", cls.refs(places["normandie"]))
        cls.merge_values(
            cls.components["open"],
            "component",
            date_start_of_production_time="1380-01-01",
            production_date_end_of_the_begin_="1385-12-31",
            date_end_of_production_time="1390-12-31",
            production_date_end_of_the_end_="1395-12-31",
            type_of_production_time=True,
        )
        cls.components["bare"] = new("component", "f. 2r — bare")
        tile(
            cls.components["bare"],
            "item_visual_is_part_of_document",
            cls.refs(cls.documents["open"]),
        )
        cls.analyses["bare"] = new("analysis", "X04 — f. 2r")
        tile(
            cls.analyses["bare"], "component_observed", cls.refs(cls.components["bare"])
        )
        cls.materials = {
            "vermilion": cls.characterized(
                "Vermilion, red ground",
                cls.components["open"],
                cls.analyses["open"],
                VERMILION,
                LOW,
                alt="Cinnabar",
            ),
            "lead": cls.characterized(
                "Lead white",
                cls.components["open"],
                cls.analyses["open"],
                LEAD_WHITE,
                HIGH,
            ),
            "smalt": cls.characterized(
                "Smalt", cls.components["bare"], cls.analyses["bare"], SMALT, HIGH
            ),
        }
        mod = cls.modification = new("modification", "Repainting of the initial")
        tile(mod, "document_modified", cls.refs(cls.components["open"]))
        cls.tile_values(
            mod,
            "modification",
            date_start_of_production_time="1420-01-01",
            date_end_of_modification_time="1430-12-31",
            type_of_modification_time=True,
        )
        tile(mod, "took_place_at_place", cls.refs(places["abbey"]))
        tile(mod, "observed_by_characterisation", cls.refs(cls.characterization))
        alt = cls.alteration = new("alteration", "Darkening of the vermilion")
        tile(alt, "object_altered", cls.refs(cls.documents["open"]))
        cls.tile_values(
            alt,
            "alteration",
            alteration_process_start_date="1700-01-01",
            alteration_process_end_date="1800-12-31",
        )
        tile(alt, "alteration_took_place_at_place", cls.refs(places["lyon"]))
        tile(
            alt,
            "occured_in_presence_of_material",
            cls.reference_value(VERMILION, "Vermilion"),
        )
        tile(
            cls.analyses["open"],
            "analysis_took_place_at_place",
            cls.refs(places["lab"]),
        )
        cls.tile_values(
            cls.samples["s1"],
            "sample",
            date_start_of_of_sample_taking="2023-02-01",
            date_end_of_sample_taking="2023-02-02",
        )
        tile(
            cls.samples["s1"],
            "location_of_sampling_taking_activity",
            cls.refs(places["hidden"]),
        )
        cls.documents["own"] = cls.produced(
            "Ms 300", places["paris"], collection(point(OWN)), dated=True
        )
        cls.documents["derived"] = cls.produced(
            "Ms 301",
            places["lyon"],
            collection(point(OWN), {"msDerivedFrom": {"place": "x"}}),
            dated=False,
        )
        cls.documents["unanalysed"] = new("document", "Ms 302")
        cls.tile_values(
            cls.documents["unanalysed"],
            "document",
            production_at_place=cls.refs(places["paris"]),
        )

    @classmethod
    def characterized(cls, name, component, analysis, uri, confidence, alt=None):
        found = cls.new_resource("characterization", name)
        cls.tile(found, "object_observed", cls.refs(component))
        cls.tile(found, "evidence_analyses", cls.refs(analysis))
        cls.tile_values(
            found,
            "characterization",
            identified_material=cls.reference_value(uri, name.split(",")[0], alt=alt),
            material_confidence=cls.reference_value(
                confidence, confidence.rsplit("/", 1)[-1]
            ),
        )
        return found

    @classmethod
    def produced(cls, name, place, geometry, dated):
        document = cls.new_resource("document", name)
        values = {
            "production_at_place": cls.refs(place),
            "literal_location_of_production": geometry,
        }
        if dated:
            values.update(
                date_start_of_production_time="1250-01-01",
                date_end_of_production_time="1260-12-31",
            )
        cls.tile_values(document, "document", **values)
        analysis = cls.new_resource("analysis", f"X — {name}")
        cls.tile(analysis, "component_observed", cls.refs(document))
        return document

    @classmethod
    def merge_values(cls, resource, slug, **values):
        nodes = [cls.nodes[(slug, alias)] for alias in values]
        tile = TileModel.objects.get(
            resourceinstance=resource, nodegroup_id=nodes[0].nodegroup_id
        )
        TileModel.objects.filter(pk=tile.pk).update(
            data={**tile.data, **{str(n.nodeid): values[n.alias] for n in nodes}}
        )

    def bundle(self):
        from manuspectrum.utils.public_visibility import visible_set
        from manuspectrum.views.explorer.service import build_bundle

        return build_bundle(self.anonymous, "en", visible_set(self.anonymous))

    def events_of(self, bundle, kind, carrier):
        return [
            e
            for e in bundle.events
            if e["type"] == kind and e["carrier"]["id"] == str(carrier.pk)
        ]
