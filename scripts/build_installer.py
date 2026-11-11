"""Build the portable installer entirely from this checkout, without network access."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import zlib

ROOT = Path(__file__).resolve().parents[1]
FILES = ["SKILL.md", "agents/openai.yaml", "references/tools.md",
         "scripts/research.py", "scripts/research_reader.py", "scripts/research_providers.py", "references/providers.md", "assets/icon.svg", "scripts/research_catalog.py", "references/source-registry.json", "references/sources.md", "scripts/research_reading.py", "references/reading.md"]


def build(output=None):
    skill = ROOT / "skills" / "deep-research-agent"
    files = {name: (skill/name).read_text(encoding="utf-8") for name in FILES}
    raw = json.dumps(files, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    template = Path(__file__).with_name("installer_template.py").read_text(encoding="utf-8")
    output = Path(output) if output else ROOT / "Install_Deep_Research_Agent.py"
    text = template.replace("__RESEARCH_PAYLOAD__", base64.b64encode(zlib.compress(raw, 9)).decode())
    text = text.replace("__RESEARCH_SHA256__", hashlib.sha256(raw).hexdigest())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(build(args.output))
