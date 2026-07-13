import os
import sys

# Point Tcl/Tk at the script libraries bundled inside _internal.
_base = os.path.join(os.path.dirname(sys.executable), '_internal')
os.environ.setdefault('TCL_LIBRARY', os.path.join(_base, 'tcl8.6'))
os.environ.setdefault('TK_LIBRARY',  os.path.join(_base, 'tk8.6'))
