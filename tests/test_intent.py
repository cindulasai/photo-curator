from curator.chat.intent import parse_intent
from curator.config import load_config
from curator.model import MockModel

PS = "prompt_suffix"
# (user text, canned model deltas). The MockModel returns them; the test proves
# the plumbing accepts every whitelisted shape and the whitelist blocks the rest.
GOLDEN = [
    ("be stricter about blur", [{"path": "triage.blur_sharp_min", "value": 80, "why": "stricter"}]),
    ("be more forgiving about blurry shots", [{"path": "triage.blur_sharp_min", "value": 40, "why": "looser"}]),
    ("really crack down on soft photos", [{"path": "triage.blur_sharp_min", "value": 80, "why": "stricter"}]),
    ("don't be so picky about focus", [{"path": "triage.blur_sharp_min", "value": 40, "why": "looser"}]),
    ("tighten up on dark photos", [{"path": "triage.black_extreme", "value": 70, "why": "stricter dark"}]),
    ("allow darker photos through", [{"path": "triage.black_extreme", "value": 95, "why": "looser dark"}]),
    ("be strict about overexposed shots", [{"path": "triage.white_extreme", "value": 70, "why": "stricter"}]),
    ("I hate blurry pictures", [{"path": "triage.blur_sharp_min", "value": 80, "why": "stricter"}]),
    ("keep even slightly soft photos", [{"path": "triage.blur_sharp_min", "value": 40, "why": "looser"}]),
    ("quality bar should be high", [{"path": "triage.blur_sharp_min", "value": 80, "why": "stricter"}]),
    ("I don't care about food photos", [{"path": "buckets.disable", "op": "append", "value": "food-drink", "why": "hide food"}]),
    ("skip food pictures", [{"path": "buckets.disable", "op": "append", "value": "food-drink", "why": "hide food"}]),
    ("no screenshots please", [{"path": "buckets.disable", "op": "append", "value": "screenshots", "why": "hide"}]),
    ("hide the vehicles category", [{"path": "buckets.disable", "op": "append", "value": "vehicles", "why": "hide"}]),
    ("I never want to see receipts", [{"path": "buckets.disable", "op": "append", "value": "documents-receipts", "why": "hide"}]),
    ("drop urban architecture", [{"path": "buckets.disable", "op": "append", "value": "urban-architecture", "why": "hide"}]),
    ("remove the pets bucket", [{"path": "buckets.disable", "op": "append", "value": "pets-animals", "why": "hide"}]),
    ("no whiteboard photos", [{"path": "buckets.disable", "op": "append", "value": "whiteboards-notes", "why": "hide"}]),
    ("hide products and shopping", [{"path": "buckets.disable", "op": "append", "value": "products-shopping", "why": "hide"}]),
    ("I don't need the hobbies bucket", [{"path": "buckets.disable", "op": "append", "value": "hobbies-activities", "why": "hide"}]),
    ("add a bucket for my paintings", [{"path": "buckets.custom", "op": "append", "value": {"key": "my-artwork", "description": "Paintings and drawings made by me"}, "why": "custom"}]),
    ("make a category for latte art", [{"path": "buckets.custom", "op": "append", "value": {"key": "latte-art", "description": "Latte art and coffee presentation shots"}, "why": "custom"}]),
    ("focus on my daughter", [{"path": PS, "op": "append", "value": "The owner especially treasures photos of their daughter; weight her photos highly.", "why": "focus"}]),
    ("my kids matter most", [{"path": PS, "op": "append", "value": "Photos of the owner's children matter most; weight them highly.", "why": "focus"}]),
    ("prioritize photos with grandparents", [{"path": PS, "op": "append", "value": "Weight photos including grandparents highly.", "why": "focus"}]),
    ("I love golden hour shots", [{"path": PS, "op": "append", "value": "The owner loves golden-hour light; score such photos generously.", "why": "taste"}]),
    ("candid moments over posed ones", [{"path": PS, "op": "append", "value": "Prefer candid moments over posed shots.", "why": "taste"}]),
    ("I prefer landscapes to portraits", [{"path": PS, "op": "append", "value": "The owner prefers landscapes over portraits.", "why": "taste"}]),
    ("weight emotional moments heavily", [{"path": "rubric.emotional", "value": 0.4, "why": "user emphasis"}]),
    ("composition matters more to me", [{"path": "rubric.composition_light", "value": 0.25, "why": "user emphasis"}]),
    ("surprise me - value unusual shots", [{"path": "rubric.uniqueness", "value": 0.2, "why": "user emphasis"}]),
    ("scenery is what I care about", [{"path": "rubric.scene_appeal", "value": 0.2, "why": "user emphasis"}]),
    ("skip the WhatsApp folder", [{"path": "skip_globs", "op": "append", "value": "WhatsApp/*", "why": "skip"}]),
    ("ignore anything under Downloads", [{"path": "skip_globs", "op": "append", "value": "Downloads/*", "why": "skip"}]),
    ("don't touch the 2019 subfolder", [{"path": "skip_globs", "op": "append", "value": "2019/*", "why": "skip"}]),
    ("exclude edited copies", [{"path": "skip_globs", "op": "append", "value": "*edited*", "why": "skip"}]),
    ("skip screenshots folder", [{"path": "skip_globs", "op": "append", "value": "Screenshots/*", "why": "skip"}]),
    ("only 50 top picks", [{"path": "top_picks.target", "value": 50, "why": "user cap"}]),
    ("give me a tight best-of, 20 photos", [{"path": "top_picks.target", "value": 20, "why": "user cap"}]),
    ("I want a big highlights set", [{"path": "top_picks.target", "value": 200, "why": "user size"}]),
    ("no more than 5 per event", [{"path": "top_picks.max_per_event", "value": 5, "why": "user cap"}]),
    ("cap highlights at 100", [{"path": "top_picks.cap", "value": 100, "why": "user cap"}]),
    ("more variety per trip", [{"path": "top_picks.max_per_event", "value": 25, "why": "variety"}]),
    ("both stricter blur and no food", [{"path": "triage.blur_sharp_min", "value": 80, "why": "stricter"},
                                        {"path": "buckets.disable", "op": "append", "value": "food-drink", "why": "hide"}]),
    ("focus on family and skip receipts", [{"path": PS, "op": "append", "value": "Weight family photos highly.", "why": "focus"},
                                           {"path": "buckets.disable", "op": "append", "value": "documents-receipts", "why": "hide"}]),
    ("kids first, strict quality", [{"path": PS, "op": "append", "value": "Photos of children matter most.", "why": "focus"},
                                    {"path": "triage.blur_sharp_min", "value": 80, "why": "stricter"}]),
    ("hide food, hide pets", [{"path": "buckets.disable", "op": "append", "value": "food-drink", "why": "hide"},
                              {"path": "buckets.disable", "op": "append", "value": "pets-animals", "why": "hide"}]),
    ("value real laughter", [{"path": PS, "op": "append", "value": "Genuine laughter is the owner's favorite thing; weight it highly.", "why": "taste"}]),
    ("beach days are special to us", [{"path": PS, "op": "append", "value": "Beach outings are special to this family; weight them highly.", "why": "taste"}]),
    ("treat concerts as keepers even in low light", [{"path": PS, "op": "append", "value": "Concert photos in low light are keepers, not exposure rejects.", "why": "taste"}]),
]

def _mock_for(canned):
    return MockModel(lambda paths, prompt, schema: canned)

def test_golden_suite_all_50_accepted():
    cfg = load_config(None)
    assert len(GOLDEN) == 50
    for text, deltas in GOLDEN:
        out = parse_intent(_mock_for({"deltas": deltas, "reply": "done"}), cfg, text)
        assert out["deltas"] == deltas, text
        assert out["reply"] == "done"

def test_model_offers_bad_path_gets_retry_then_fallback():
    calls = {"n": 0}
    def handler(paths, prompt, schema):
        calls["n"] += 1
        return {"deltas": [{"path": "llm.seed", "value": 7, "why": "nope"}],
                "reply": "tried"}
    out = parse_intent(MockModel(handler), load_config(None), "change the seed")
    assert calls["n"] == 2                       # one corrective retry
    assert out["deltas"] == []
    assert "couldn't turn that into a safe change" in out["reply"]

def test_retry_recovers():
    replies = iter([
        {"deltas": [{"path": "model", "value": "x", "why": ""}], "reply": "bad"},
        {"deltas": [{"path": "triage.blur_sharp_min", "value": 80, "why": "ok"}], "reply": "fixed"},
    ])
    out = parse_intent(MockModel(lambda *a: next(replies)),
                       load_config(None), "stricter blur")
    assert out["deltas"][0]["path"] == "triage.blur_sharp_min"

def test_question_passes_run_state():
    seen = {}
    def handler(paths, prompt, schema):
        seen["prompt"] = prompt
        return {"deltas": [], "reply": "3 rejected so far"}
    out = parse_intent(MockModel(handler), load_config(None),
                       "how is it going?", run_state={"rejected": 3})
    assert out["deltas"] == [] and "rejected" in out["reply"]
    assert '"rejected": 3' in seen["prompt"]
