import os
import sys

# The hardware simulator keeps its own settings and pictures, so that trying
# things with --sim never touches the real label's records in data/.
if "--sim" in sys.argv[1:] and "MONOPINK_DATA" not in os.environ:
    os.environ["MONOPINK_DATA"] = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sim")

from .cli import main  # noqa: E402

sys.exit(main())
