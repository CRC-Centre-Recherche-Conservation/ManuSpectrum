"""Coordinates of the « Imaging layers » proposal in the Analysis model.

**Pure data**: no Django imports, so a migration can read it. The manifest
nodegroup collects its own node, so node id == nodegroup id; a migration cannot
resolve an alias, the proposal checks the alias at run time.
"""

from manuspectrum.constants.xy_presets import ANALYSIS_GRAPH_ID

__all__ = ["ANALYSIS_GRAPH_ID", "IMAGING_MANIFEST_NODEGROUP_ID"]

#: « Chemical imaging manifest » — manifest datatype, cardinality n; parent
#: nodegroup of the « Imaging layers » tiles.
IMAGING_MANIFEST_NODEGROUP_ID = "9764a2c7-fc1b-46dd-8b4a-8b86588a0294"
