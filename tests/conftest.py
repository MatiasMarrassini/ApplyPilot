import os
import tempfile

# applypilot.config reads APPLYPILOT_DIR at import time, so point it at a
# throwaway directory before any test imports the package.
os.environ["APPLYPILOT_DIR"] = tempfile.mkdtemp(prefix="applypilot-test-")
