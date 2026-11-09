"""Texts of the Pace window: what Steady pace and "Per request" do, when to use them and what they risk.

Every entry says first what it lets the user do, then gives one example that ends in a result. The numbers come from
pace.py (interval formula, shipped limits) and from the blind tests recorded in the project notes."""

FIELDS = ("About", "Example", "Use when", "Risk", "Know")


def steady():
    return {
        "title": "Steady pace",
        "About": "Lets the app set the pause between requests itself, so the model's per-minute limit is never exceeded.",
        "Example": "For a model that allows 15 requests a minute and answers in 3 s, the pause is 1.4 s: the run goes at "
                   "about 13 requests a minute and never meets the limit.",
        "Use when": "Always: it is on by itself and has nothing to set.",
        "Risk": "A run starts cautious: until 8 requests are measured the pause is 4.4 s on a 15-a-minute model, so the "
                "first run is slower; the measured speed is used from the next start (resume or key switch).",
        "Know": "If a limit is still reached, the app moves to the next key or model, or waits and continues by itself.",
    }


def per_request(n):
    if n <= 1:
        return {
            "title": "1 per request",
            "About": "Lets you translate one paragraph per request, the most careful setting.",
            "Example": "A chapter of 200 paragraphs takes 200 requests; every paragraph is translated with the prompt and, "
                       "when Context is on, the paragraphs before it.",
            "Use when": "Best fidelity matters more than speed: short books, dialogue, names and glossary rules you check "
                        "closely.",
            "Risk": "The most requests: a key that allows 500 requests a day covers about 500 paragraphs a day.",
            "Know": "A paragraph that fails or is blocked is retried alone and costs only itself.",
        }
    out = {
        "title": "%d per request" % n,
        "About": "Lets you send %d neighbouring paragraphs of a chapter in one request." % n,
        "Example": "At %d, a chapter of 200 paragraphs takes %d requests instead of 200, so a key that allows 500 requests "
                   "a day covers about %d paragraphs a day." % (n, -(-200 // n), 500 * n),
        "Use when": "The book is long, the daily limit is the bottleneck or time matters; run Test on the first pages and "
                    "compare with 1 per request before a full run.",
        "Risk": "In a blind test on one chapter 5 and 10 per request showed no measurable quality loss, but the test is "
                "small. In this mode the engine drops its own safety, top_k and output-length settings, a paragraph can "
                "come back shifted onto its neighbour without the engine noticing (seen once in 6 runs of another model), "
                "and a failed request loses %d paragraphs at once." % n,
        "Know": "Groups never cross a chapter; after a stop the run continues at the group where it stopped. Needs the "
                "engine's Python 3.12 or newer.",
    }
    if n >= 20:
        out["Use when"] = "Only to experiment: this size has not been tested."
        out["Risk"] = "Not tested. A miss costs %d paragraphs at once and long answers may be cut." % n
    return out


def sections(n):
    """[(title, [(field, text), ...])] for the Pace window: Steady pace, then the chosen group size."""
    out = []
    for d in (steady(), per_request(n)):
        out.append((d["title"], [(f, d[f]) for f in FIELDS]))
    return out
