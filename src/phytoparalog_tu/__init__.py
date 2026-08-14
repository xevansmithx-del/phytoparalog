"""Optional ToolUniverse plugin for PhytoParalog.

The scientific engine lives in :mod:`phytoparalog`. ToolUniverse discovers this
package through its installed entry point and imports ``tool.py`` to register the
adapter class.
"""

PLUGIN_VERSION = "0.1.1"

__all__ = ["PLUGIN_VERSION"]
