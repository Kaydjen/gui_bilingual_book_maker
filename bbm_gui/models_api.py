"""The models a Gemini key can list, reduced to the ones that can translate text."""
import json
import re
import urllib.request

URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"
# names that generate something other than text, or are not plain chat models
SKIP = re.compile(r"tts|image|live|embedding|audio|transcribe|robotics|computer-use|antigravity|deep-research|lyria|"
                  r"nano-banana|customtools|omni|aqa|argon", re.I)


def usable(models):
    """models: items of the API answer. Returns names (without 'models/') that can generate text, newest first."""
    names = []
    for m in models:
        name = str(m.get("name", "")).replace("models/", "", 1)
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        if not re.match(r"(gemini|gemma)-", name) or SKIP.search(name):
            continue
        names.append(name)

    def order(n):
        nums = [int(x) for x in re.findall(r"\d+", n)]
        return (0 if n.startswith("gemini") else 1, not nums, [-x for x in nums], n)  # "-latest" aliases go last

    return sorted(set(names), key=order)


def fetch(key, timeout=20):
    req = urllib.request.Request(URL, headers={"x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return usable(data.get("models", []))
