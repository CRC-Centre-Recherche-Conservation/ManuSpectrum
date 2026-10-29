"""Starting summary configurations, attached by migration 0004.

Curators edit them afterwards in the graph designer (Functions tab); this
module is only what a fresh database starts from. Every entry is written in the
shape ``normalize_config`` returns, so the migration stores it untouched and
re-running the migration never rewrites a curator's edit into a different
normal form. Aliases were read from the ``nodes`` table on 22/09.
"""

CONFIG_VERSION = 1


def _rollup(key, en, fr, path, distinct=None, limit=8, max_related=500):
    aggregate = [{"op": "count"}]
    if distinct:
        aggregate.append(
            {"op": "distinct", "alias": distinct, "style": "chip", "limit": limit}
        )
    return {
        "key": key,
        "label": {"en": en, "fr": fr},
        "path": path,
        "aggregate": aggregate,
        "max_related": max_related,
    }


def _hop(slug, alias, direction):
    return {"graph_slug": slug, "alias": alias, "direction": direction}


SEED_CONFIGS = {
    "document": {
        "config_version": CONFIG_VERSION,
        "fields": [
            {"alias": "label_of_name", "style": "text"},
            {"alias": "date_start_of_production_time", "style": "date"},
            {"alias": "date_end_of_production_time", "style": "date"},
            {"alias": "period_production", "style": "chip", "max_values": 3},
            {
                "alias": "techniques_used_during_production",
                "style": "chip",
                "max_values": 5,
            },
            {"alias": "production_at_place", "style": "link", "max_values": 3},
            {"alias": "current_location", "style": "link"},
        ],
        "rollups": [
            _rollup(
                "components",
                "Components",
                "Composants",
                [_hop("component", "item_visual_is_part_of_document", "incoming")],
                distinct="color_features",
                limit=10,
            ),
            _rollup(
                "analyses",
                "Analyses",
                "Analyses",
                [
                    _hop("component", "item_visual_is_part_of_document", "incoming"),
                    _hop("analysis", "component_observed", "incoming"),
                ],
                distinct="analysis_technique_used",
            ),
            _rollup(
                "characterizations",
                "Characterizations",
                "Caractérisations",
                [_hop("characterization", "object_observed", "incoming")],
                distinct="identified_material",
                limit=10,
                max_related=200,
            ),
        ],
    },
    "component": {
        "config_version": CONFIG_VERSION,
        "fields": [
            {"alias": "label_of_name", "style": "text"},
            {"alias": "color_features", "style": "chip", "max_values": 5},
            {"alias": "description_features", "style": "chip", "max_values": 3},
            {
                "alias": "techniques_used_during_production",
                "style": "chip",
                "max_values": 5,
            },
            {"alias": "production_period", "style": "chip", "max_values": 3},
            {"alias": "item_visual_is_part_of_document", "style": "link"},
        ],
        "rollups": [
            _rollup(
                "analyses",
                "Analyses",
                "Analyses",
                [_hop("analysis", "component_observed", "incoming")],
                distinct="analysis_technique_used",
            ),
            _rollup(
                "characterizations",
                "Characterizations",
                "Caractérisations",
                [_hop("characterization", "object_observed", "incoming")],
                distinct="identified_material",
                limit=10,
                max_related=200,
            ),
        ],
    },
    "analysis": {
        "config_version": CONFIG_VERSION,
        "fields": [
            {"alias": "label_of_name", "style": "text"},
            {"alias": "analysis_technique_used", "style": "chip", "max_values": 3},
            {"alias": "analysis_start_date", "style": "date"},
            {"alias": "analysis_end_date", "style": "date"},
            {"alias": "component_observed", "style": "link"},
            {"alias": "analysis_by_project", "style": "link"},
            {"alias": "measurement_point_data", "style": "image"},
        ],
        "rollups": [
            _rollup(
                "characterizations",
                "Characterizations",
                "Caractérisations",
                [_hop("characterization", "evidence_analyses", "incoming")],
                distinct="identified_material",
                limit=10,
                max_related=200,
            ),
        ],
    },
    "characterization": {
        "config_version": CONFIG_VERSION,
        "fields": [
            {"alias": "label_of_name", "style": "text"},
            {"alias": "object_observed", "style": "link", "max_values": 3},
            {"alias": "layer_type", "style": "chip", "max_values": 3},
            {"alias": "identified_material", "style": "chip", "max_values": 5},
            {"alias": "detected_elements", "style": "chip", "max_values": 5},
            {"alias": "material_proportion_value", "style": "number"},
            {"alias": "material_proportion_unit", "style": "chip", "max_values": 1},
            {"alias": "material_confidence", "style": "chip", "max_values": 1},
            {"alias": "color_aspect", "style": "chip", "max_values": 3},
        ],
        "rollups": [
            # The distinct alias belongs to the TARGET graph of the hop
            # (analysis), which the service resolves from the node's
            # config["graphs"]; an outgoing hop is the only case where the two
            # differ from the hop's own graph_slug.
            _rollup(
                "evidence_analyses",
                "Evidence analyses",
                "Analyses à l'appui",
                [_hop("characterization", "evidence_analyses", "outgoing")],
                distinct="analysis_technique_used",
            ),
        ],
    },
    "sample": {
        "config_version": CONFIG_VERSION,
        "fields": [
            {"alias": "label_of_name", "style": "text"},
            {"alias": "sampling_taking_from_object", "style": "link", "max_values": 3},
            {"alias": "date_start_of_of_sample_taking", "style": "date"},
            {
                "alias": "technique_used_by_sample_taking",
                "style": "chip",
                "max_values": 3,
            },
            {"alias": "type_of_sample_taking", "style": "chip", "max_values": 3},
            {"alias": "location_of_sample_object", "style": "link"},
        ],
        "rollups": [
            _rollup(
                "analyses",
                "Analyses",
                "Analyses",
                [_hop("analysis", "sample_used", "incoming")],
                distinct="analysis_technique_used",
            ),
        ],
    },
}
