from __future__ import annotations
import json, re
from importlib.resources import files
from .config import active_buckets

_RUBRIC_TEXT = """Score each axis 0-4 (0 = absent, 4 = exceptional). Judge like a human curator, not a camera:
- emotional: genuine feeling captured - laughter, embrace, tears of joy, quiet tenderness, a milestone moment. A forced pose scores low; a real instant scores high.
- people_engagement: are subjects present, engaged, eyes open, expressions natural and alive?
- composition_light: strength of composition and beauty or interest of the light.
- scene_appeal: is the subject itself appealing - a grand landscape, striking architecture, beautiful food?
- novelty: does this image feel unlike a typical snapshot - a surprising angle, moment, or subject?"""


def _taxonomy_block(cfg: dict) -> str:
    lines = [f"- {b['key']}: {b['description']}" + ("  [UTILITY]" if b["utility"] else "")
             for b in active_buckets(cfg)]
    return "\n".join(lines)


def render(name: str, cfg: dict, **subs) -> str:
    text = files("curator").joinpath(f"prompts/{name}.md").read_text()
    text = re.sub(r"^<!-- version: \d+ -->\n", "", text)
    replacements = {"TAXONOMY": _taxonomy_block(cfg), "RUBRIC": _RUBRIC_TEXT, **subs}
    for key, val in replacements.items():
        text = text.replace(f"<<{key}>>", str(val))
    if "<<" in text:
        missing = re.findall(r"<<([A-Z_]+)>>", text)
        raise ValueError(f"unfilled placeholders in {name}: {missing}")
    return text


def load_schema(name: str) -> dict:
    return json.loads(files("curator").joinpath(f"schemas/{name}.schema.json").read_text())


def versions() -> dict[str, int]:
    out = {"json_repair": 1}
    for f in sorted(files("curator").joinpath("prompts").iterdir(),
                    key=lambda f: f.name):
        if f.name.endswith(".md"):
            m = re.match(r"<!-- version: (\d+) -->", f.read_text().split("\n", 1)[0])
            out[f.name[:-3]] = int(m.group(1)) if m else 0
    return out
