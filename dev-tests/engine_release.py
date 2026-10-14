"""The release of the GS1 Barcode Syntax Engine the installation uses, written once in docker-compose.yml
(x-gs1-syntax-engine; Documentation/adr/0003-gs1-rules-from-the-dictionary.md). Test programs compare the
engines they find with it."""
import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parent.parent / "docker-compose.yml"
PATTERN = re.compile(r'^x-gs1-syntax-engine:\s*&gs1-syntax-engine\s*"([^"]+)"', re.M)


def engine_release() -> str:
    """"1.4.1", from docker-compose.yml; an error when it is not there."""
    match = PATTERN.search(COMPOSE.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"x-gs1-syntax-engine not found in {COMPOSE}")
    return match.group(1)
