import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

FIXTURE = ROOT / "tests/fixtures/uat-observability.yaml"


def fixture():
    return copy.deepcopy(yaml.safe_load(FIXTURE.read_text()))
