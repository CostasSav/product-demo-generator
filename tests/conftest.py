import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "product-demo-generator"
SKILL = PLUGIN / "skills" / "product-demo-generator"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))
