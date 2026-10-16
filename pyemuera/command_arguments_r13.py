"""Compatibility imports for the historical module name.

New code imports command_arguments. JSON policy keys, builder labels and the
runtime cache attribute remain unchanged; this module exports the same callables.
"""

from .command_arguments import check, lazy
