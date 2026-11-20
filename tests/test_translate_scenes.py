"""The Translate screen as scenarios (tests/qmlharness.py, offscreen + software): every state of the accepted mock-up
(full/translate.js: ready nokeys nolang reach first alldone running retry paused other stopped replace terms quota failed elsewhere
problems problem1 queue restart sample) and its panels (replace job, discard job, replace queued item, the prompt editor with its
draft, the To drop-down, the Time popover, closing during a run and during a wait) at 100 % and 150 %, a few at the narrow 820 x 600.
A real library with real EPUBs and a real job record behind the real view-models and the real RunControl; the runner is not started
(a state is reached by the events a run sends, tests/translatedrive.py) except in the scenes that run against the fake server
(tests/fake_api.py). Asserts by objectName, red only where window_spec 7.16 says, at most one ambient animation, no QML warning;
shots go to NOVELGUI_SHOTS (default: the temp dir)."""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import qmlharness as qh  # noqa: E402
from tests import translatedemo as demo  # noqa: E402
from tests import translatescenes as ts  # noqa: E402
from tests.translatescenes import SHORT, WAIT, call, click, data, py, sel, tv  # noqa: E402

RUN = qh.have_qt()
VM = "tests.shellfactory:make"
SCALES = (1.0, 1.5)
NARROW = (820, 600)
RED = "#e5383b"
BRIGHT, TEXT, DIM, FAINT = "#f4f4f4", "#dedede", "#8a8a8a", "#5a5a5a"


def segs(r):
    """The texts of the bottom bar, [] while it is hidden."""
    if not r.item("trBar")["visible"]:
        return []
    out, k = [], 0
    while r.has("trBarText%d" % k):
        out.append(r.item("trBarText%d" % k)["text"])
        k += 1
    return out


def seg_color(r, k=0):
    return r.item("trBarText%d" % k)["color"]


def word(r, row):
    """(text, colour) of the state word of a chapter row; None when the row has none."""
    if not r.has("trWord%d" % row):
        return None
    w = r.item("trWord%d" % row)
    return (w["text"], w["color"]) if w["visible"] and w["text"] else None


def rows(r, name="trChapterList"):
    return r.item(name)["count"]


def tabs(r):
    return [t for t in ("chapters", "problems", "queue", "sample") if r.has("trTab_" + t) and r.item("trTab_" + t)["visible"]]


def event(r, name):
    vals = [v for k, v in r.events if k == name]
    return vals[-1] if vals else None


@unittest.skipUnless(RUN, "PySide6 is not available")
class Scenes(unittest.TestCase):
    def go(self, name, scales=SCALES, size=(1040, 720), tag=None, data_=None, actions=None):
        d, a = ts.SCENES[name]
        tag = tag or name + ("_narrow" if size == NARROW else "")
        return [qh.scenario("ShellScene", data_ or d, scale=k, vm=VM, actions=actions or a, tag="translate_" + tag, size=size,
                            timeout=150) for k in scales]

    def narrow(self, name):
        return self.go(name, scales=(1.0,), size=NARROW)

    def only_red(self, r, *inside, maybe=()):
        """The red of a Translate scene: nowhere, or only inside the named elements (`maybe`: it may be red there, e.g. a header
        word in the middle of its pulse)."""
        img = r.image()
        total = qh.count_red(img)
        if not inside and not maybe:
            self.assertEqual(total, 0, "no red in this state")
            return
        got = [qh.count_red(img, self.grown(r.rect(n))) for n in inside]
        for n, c in zip(inside, got):
            self.assertGreater(c, 8, "the red thing is drawn: %s" % n)
        more = [qh.count_red(img, self.grown(r.rect(n))) for n in maybe]
        self.assertEqual(sum(got) + sum(more), total, "red only inside %s" % ", ".join(inside + tuple(maybe)))

    @staticmethod
    def grown(rect, by=3):
        x, y, w, h = rect
        return (x - by, y - by, w + 2 * by, h + 2 * by)

    def assertQuiet(self, r, limit=1):
        self.assertLessEqual(r.ambient, limit, "at most one ambient animation: %s" % r.animations)

    # ------------------------------------------------------------------------------------------------ the quiet states
    def test_ready(self):
        for r in self.go("ready"):
            self.assertEqual(segs(r), ["Translate · 2703-2750"])
            self.assertEqual(seg_color(r), BRIGHT)
            self.assertEqual(tabs(r), [], "only Chapters exists: no tab strip")
            self.assertFalse(r.item("trTabs")["visible"])
            self.assertEqual(rows(r), 48)
            self.assertEqual(r.item("trToValue")["text"], "Russian")
            self.assertEqual(r.item("trFromValue")["text"], "From English")
            self.assertEqual(r.item("trFromValue")["color"], FAINT, "From is reserved and dim")
            self.assertEqual(r.item("trPromptValue")["text"], "Default")
            self.assertEqual(r.item("trPromptEdit")["text"], "✎")
            self.assertEqual(r.item("trSampleValue")["text"], "Sample")
            self.assertTrue(r.item("trTime")["visible"])
            self.assertTrue(r.item("trTimeValue")["text"].startswith("≈ "))
            self.assertFalse(r.item("trBarSat")["visible"])
            self.assertEqual([word(r, i) for i in range(5)], [None] * 5)
            self.assertTrue(r.item("trBarFill0")["w"] == 0)
            self.only_red(r)
            self.assertEqual(r.ambient, 0)
        self.narrow("ready")

    def test_no_keys(self):
        for r in self.go("nokeys"):
            self.assertEqual(segs(r), ["Add keys"])
            self.assertEqual(seg_color(r), RED)
            self.assertEqual(r.item("trSampleValue")["color"], FAINT, "Sample is dim without keys")
            self.only_red(r, "trBarText0")
        self.narrow("nokeys")

    def test_no_language(self):
        for r in self.go("nolang"):
            self.assertEqual(r.item("trToValue")["text"], "language")
            self.assertEqual(r.item("trToValue")["color"], RED)
            self.assertEqual(segs(r), ["Translate · 2703-2750"])
            self.assertEqual(seg_color(r), FAINT, "Translate is dim until the language is chosen")
            self.assertEqual(r.item("trSampleValue")["color"], FAINT)
            self.only_red(r, "trTo")
        self.narrow("nolang")

    def test_reach_is_shortened_by_a_blocked_chapter(self):
        for r in self.go("reach"):
            self.assertEqual(segs(r), ["Translate · 2725-2730"])
            self.assertEqual(word(r, 6), ("1 term", DIM), "the blocked chapter carries a dim terms mark")
            self.assertEqual(r.item("trTitle7")["color"], FAINT, "chapters past the reach are dim")
            self.assertEqual(r.item("trTitle0")["color"], TEXT)
            self.only_red(r)
            self.assertEqual(r.ambient, 0)

    def test_first_chapter_blocked(self):
        for r in self.go("first"):
            self.assertEqual(segs(r), ["Review 1 term"])
            self.assertEqual(seg_color(r), RED)
            self.assertEqual(word(r, 0), ("1 term", RED))
            self.assertEqual(r.item("step_terms")["kind"], "red")
            self.only_red(r, "trBarText0", "trWord0", maybe=("step_terms",))
            self.assertEqual(r.item("trSampleValue")["text"], "Sample · 1 unreviewed")
        self.narrow("first")

    def test_all_translated(self):
        for r in self.go("alldone"):
            self.assertEqual(segs(r), ["Retranslate · 2703-2750"])
            self.assertEqual(seg_color(r), FAINT, "the label only, dim (until core C10)")
            self.assertFalse(r.item("trTime")["visible"], "nothing left to translate: no Time pill")
            self.assertEqual(r.item("trToValue")["color"], FAINT, "the language is fixed once something is translated")
            self.assertEqual(r.item("trBarFill0")["w"], 110, "a translated chapter has the full bar")
            self.only_red(r)
            self.assertEqual(r.ambient, 0)

    # ------------------------------------------------------------------------------------------------ job states
    def test_running(self):
        for r in self.go("running"):
            self.assertEqual(segs(r), ["Stop"])
            self.assertEqual(r.item("step_translate")["kind"], "wave")
            self.assertEqual(r.item("trToValue")["color"], FAINT, "To is locked")
            self.assertEqual(r.item("trSampleValue")["color"], FAINT)
            self.assertEqual(r.item("trPromptValue")["color"], TEXT, "Prompt stays usable")
            self.assertEqual(r.item("trPromptEdit")["color"], DIM)
            fill = r.item("trBarFill0")["w"]
            self.assertTrue(0 < fill < 110, "the current chapter shows its progress: %s" % fill)
            self.assertEqual(r.item("trTitle0")["color"], BRIGHT, "the current row is bright")
            self.assertTrue(r.item("trTime")["visible"])
            self.only_red(r)
            self.assertEqual(r.ambient, 1)
        self.narrow("running")

    def test_retrying_and_paused_are_dim_words(self):
        for r in self.go("retry"):
            w = word(r, 0)
            self.assertTrue(re.fullmatch(r"Retrying 0:\d\d", w[0]), w)
            self.assertEqual(w[1], DIM)
            self.assertEqual(segs(r), ["Stop"])
            self.only_red(r)
        for r in self.go("paused"):
            w = word(r, 0)
            self.assertTrue(re.fullmatch(r"Paused 0:\d\d", w[0]), w)
            self.assertEqual(w[1], DIM)
            self.only_red(r)
            self.assertEqual(r.ambient, 1)

    def test_stopping(self):
        for r in self.go("stopping"):
            self.assertEqual(segs(r), ["Stopping…"])
            self.assertEqual(seg_color(r), FAINT)
            self.assertEqual(word(r, 0)[0], "Stopping")
            self.assertEqual(r.item("step_translate")["kind"], "wave", "the wave goes on until it really stopped")
            self.only_red(r)

    def test_another_series_runs(self):
        for r in self.go("other"):
            self.assertEqual(segs(r), ["Add to queue · 2703-2750"])
            self.assertEqual(tabs(r), ["chapters", "queue"])
            self.assertEqual(r.item("trTabCount_queue")["text"], "1")
            self.assertEqual(r.item("trTabCount_queue")["color"], FAINT)
            self.assertEqual(r.item("trSampleValue")["color"], FAINT, "Sample is dim while any job runs")
            self.assertEqual(r.item("step_translate")["kind"], "wave")
            self.only_red(r)
            self.assertEqual(r.ambient, 1)
        self.narrow("other")

    def test_stopped_job(self):
        for r in self.go("stopped"):
            self.assertEqual(segs(r), ["Continue 2730-2750"])
            self.assertEqual(seg_color(r), BRIGHT)
            self.assertTrue(r.item("trBarSat")["visible"], "••• = Discard job")
            self.assertEqual(word(r, 0), ("Stopped", BRIGHT))
            self.assertEqual(rows(r), 21)
            self.assertEqual(r.item("step_translate")["kind"], "")
            self.only_red(r)
        self.narrow("stopped")

    def test_stopped_job_and_another_selection(self):
        for r in self.go("replace"):
            self.assertEqual(segs(r), ["Continue 2730-2750", "Replace job · 2800-2819"])
            self.assertEqual(seg_color(r, 0), BRIGHT)
            self.assertEqual(seg_color(r, 1), DIM)
            self.assertEqual(rows(r), 20)
            self.assertTrue(r.item("trBarSat")["visible"])
            self.only_red(r)
        self.narrow("replace")

    def test_waiting_for_terms(self):
        for r in self.go("terms"):
            self.assertEqual(segs(r), ["Review 1 term"], "no dim Continue: it comes back with the confirmed terms")
            self.assertEqual(seg_color(r), RED)
            self.assertEqual(word(r, 1), ("1 term", RED))
            self.assertTrue(r.item("trBarSat")["visible"])
            self.assertEqual(r.item("step_terms")["kind"], "red")
            self.only_red(r, "trBarText0", "trWord1", maybe=("step_terms",))
        self.narrow("terms")

    def test_daily_quota_wait(self):
        for r in self.go("quota"):
            self.assertEqual(segs(r), ["Don't resume"])
            w = word(r, 0)
            self.assertTrue(re.fullmatch(r"Resumes \d\d:\d\d", w[0]), w)
            self.assertEqual(w[1], DIM)
            self.assertEqual(tabs(r), [], "this series' own quota wait with nothing queued: no Queue tab (mock quota, F7)")
            self.assertTrue(re.fullmatch(r"≈ .+ after \d\d:\d\d", r.item("trTimeValue")["text"]), r.item("trTimeValue")["text"])
            self.assertEqual(r.item("trSampleValue")["color"], FAINT)
            self.assertEqual(r.item("step_translate")["kind"], "", "waiting for the quota is not a red pulse")
            self.only_red(r)
        self.narrow("quota")

    def test_failed_with_a_dead_key(self):
        for r in self.go("failed"):
            self.assertEqual(segs(r), ["Settings", "Continue 2730-2750"])
            self.assertEqual(seg_color(r, 0), RED)
            self.assertEqual(seg_color(r, 1), BRIGHT)
            self.assertEqual(word(r, 0), ("Key invalid", RED))
            self.assertEqual(r.item("step_translate")["kind"], "attention")
            self.assertTrue(r.item("trBarSat")["visible"])
            self.only_red(r, "trBarText0", "trWord0", maybe=("step_translate",))
            self.assertQuiet(r)
        self.narrow("failed")

    def test_running_in_another_window(self):
        for r in self.go("elsewhere"):
            self.assertEqual(segs(r), [], "no bar: nothing here can start or stop it")
            self.assertEqual(word(r, 0), ("Busy elsewhere on this PC", DIM))
            self.assertEqual(r.item("trSampleValue")["color"], FAINT)
            self.assertEqual(r.item("trPromptValue")["color"], FAINT)
            self.only_red(r)
        self.narrow("elsewhere")

    # ------------------------------------------------------------------------------------------------ problems
    def test_problems_tab(self):
        for r in self.go("problems"):
            self.assertEqual(tabs(r), ["chapters", "problems"])
            self.assertEqual(r.item("trTabCount_problems")["text"], "3")
            self.assertEqual(r.item("trTabCount_problems")["color"], RED, "a block failed: its count is red")
            self.assertEqual(rows(r, "trProblemList"), 3)
            self.assertEqual(r.item("problemChapter0")["text"], "Chapter 2699 - Moon Gate")
            self.assertEqual(r.item("problemReason0")["text"], "empty")
            self.assertEqual(segs(r), ["Check 2711"], "only chapters with a translation or a failed block can be checked")
            self.assertFalse(r.item("trEditor")["visible"])
            self.assertEqual(r.item("trPane")["h"] > 450, True, "no editor: the pane runs to the bottom")
            self.only_red(r, "trTabCount_problems")
            self.assertEqual(r.ambient, 0)
        self.narrow("problems")

    def test_a_problem_opens_the_row_editor(self):
        for r in self.go("problem1"):
            self.assertTrue(r.item("trEditor")["visible"])
            self.assertEqual(r.item("problemSourceText")["text"], "Paragraph 1 of chapter 50, with a few words to translate.")
            self.assertEqual(r.item("problemEdit")["text"], "", "a failed block has no translation yet")
            self.assertEqual(r.item("problemRetry")["text"], "Retry")
            self.assertEqual(r.item("problemKeep")["text"], "Keep original")
            self.assertFalse(r.item("problemIgnore")["visible"], "Ignore is for findings only")
            self.assertEqual(r.item("problemSave")["text"], "Save")
            self.assertFalse(r.item("trBar")["visible"], "the editor replaces the bar")
            self.assertTrue(r.item("trEditor")["y"] > r.item("trPane")["y"] + r.item("trPane")["h"] - 1, "the editor sits under the pane")
            self.only_red(r, "trTabCount_problems")
        self.narrow("problem1")

    def test_check_running(self):
        for r in self.go("checking"):
            self.assertEqual(segs(r), ["Checking 2703-2750 · 40 %"])
            self.assertEqual(seg_color(r), FAINT)
            self.assertTrue(r.item("trBarProgress0")["visible"], "a thin line shows how far the check is")
            self.only_red(r, "trTabCount_problems")

    # ------------------------------------------------------------------------------------------------ queue
    def test_queue_tab_with_a_running_job(self):
        for r in self.go("queue"):
            self.assertEqual(tabs(r), ["chapters", "queue"])
            self.assertEqual(r.item("trTabCount_queue")["text"], "2")
            self.assertEqual(r.item("queueStart0")["text"], "now")
            self.assertEqual(r.item("queueStart0")["color"], BRIGHT)
            self.assertEqual(r.item("queueName0")["text"], "Gamma")
            self.assertEqual(r.item("queueName0")["color"], BRIGHT)
            self.assertEqual(r.item("queueDetail0")["color"], DIM)
            self.assertTrue(r.item("queueBar0")["visible"] and r.item("queueStop0")["visible"])
            self.assertEqual(r.item("queuePercent0")["text"], "0 %")
            self.assertTrue(r.item("queueStart1")["text"].startswith("≈ "))
            self.assertEqual(r.item("queueName1")["text"], "Delta")
            self.assertFalse(r.item("queueStop1")["visible"])
            self.assertEqual(r.item("queueMoves1")["opacity"], 0, "↑ ↓ show on hover only")
            self.assertEqual(segs(r), ["Add to queue · 2703-2750"])
            self.only_red(r)
            self.assertEqual(r.ambient, 1)
        self.narrow("queue")

    def test_queue_after_a_restart(self):
        for r in self.go("restart"):
            self.assertEqual(r.item("queueStart0")["text"], "next")
            self.assertEqual(r.item("queueStart1")["text"], "then")
            self.assertEqual(segs(r), ["Continue queue"])
            self.assertEqual(seg_color(r), BRIGHT)
            self.assertFalse(r.item("queueBar0")["visible"], "nothing runs: no bar, no Stop")
            self.assertEqual(r.item("step_translate")["kind"], "", "a restored queue never pulses")
            self.only_red(r)
            self.assertEqual(r.ambient, 0)
        self.narrow("restart")

    def test_queue_waiting_for_the_quota(self):
        for r in self.go("qwait"):
            self.assertTrue(re.fullmatch(r"\d\d:\d\d", r.item("queueStart0")["text"]))
            self.assertTrue(re.fullmatch(r"Resumes \d\d:\d\d", r.item("queueWait0")["text"]))
            self.assertTrue(r.item("queueDontResume0")["visible"])
            self.assertFalse(r.item("queueBar0")["visible"])
            self.assertTrue(r.item("queueStart1")["text"].startswith("≈ "))
            self.only_red(r)

    def test_queue_stopped_at_an_item(self):
        for r in self.go("qstuck"):
            self.assertTrue(r.item("queueWhy0")["visible"])
            self.assertIn("Book 9", r.item("queueWhy0")["text"])
            self.assertEqual(r.item("queueWhy0")["color"], RED)
            self.assertEqual(segs(r), ["Continue queue"])
            self.assertEqual(r.item("step_translate")["kind"], "attention", "9.12: the header pulses red")
            self.only_red(r, "queueWhy0", maybe=("step_translate",))
        self.narrow("qstuck")

    # ------------------------------------------------------------------------------------------------ sample
    def test_sample_tab(self):
        for r in self.go("sample"):
            self.assertEqual(tabs(r), ["chapters", "sample"])
            self.assertEqual(r.item("sampleTitle")["text"], "Sample · 1 term unreviewed")
            self.assertEqual(r.item("sampleTitle")["color"], BRIGHT, "unreviewed terms show in the title, no red")
            self.assertEqual(r.item("sampleSub")["text"], "chapter 2703 · first 50 blocks")
            self.assertEqual(r.item("sampleSource1")["color"], DIM)
            self.assertEqual(r.item("sampleTarget1")["color"], BRIGHT)
            self.assertEqual(r.item("sampleTarget1")["text"], ts.SAMPLE[1])
            self.assertEqual(r.item("trSampleValue")["text"], "Sample · 1 unreviewed")
            self.assertEqual(r.ambient, 0)
        self.narrow("sample")

    def test_sample_running(self):
        for r in self.go("sampling"):
            self.assertEqual(r.item("trSampleValue")["text"], "Sample 12 / 50")
            self.assertEqual(r.item("trSampleValue")["color"], TEXT, "a click stops the sample: it stays usable")
            self.assertTrue(r.item("sampleSkeleton0")["visible"], "answers still to come are quiet bars")
            self.assertQuiet(r)

    # ------------------------------------------------------------------------------------------------ panels
    def test_replace_job_panel(self):
        for r in self.go("replacepanel"):
            self.assertTrue(r.item("jobCard")["visible"])
            self.assertEqual(r.item("jobPanelTitle")["text"], "Replace the job?")
            self.assertIn("has an unfinished job", r.item("jobText")["text"])
            self.assertIn("Everything translated stays.", r.item("jobText")["text"])
            self.assertEqual(r.item("jobOk")["text"], "Replace job")
            self.assertEqual(r.item("jobCancel")["text"], "Cancel")
            self.only_red(r)
        self.narrow("replacepanel")

    def test_discard_job_panel(self):
        for r in self.go("discardpanel"):
            self.assertTrue(r.item("jobCard")["visible"])
            self.assertEqual(r.item("jobPanelTitle")["text"], "Discard the job?")
            self.assertEqual(r.item("jobOk")["text"], "Discard")
            self.assertIn("will not be continued", r.item("jobText")["text"])
            self.only_red(r)

    def test_replace_queued_item_panel(self):
        for r in self.go("itempanel"):
            self.assertTrue(r.item("jobCard")["visible"])
            self.assertEqual(r.item("jobPanelTitle")["text"], "Replace the queued item?")
            self.assertIn("The queue already has", r.item("jobText")["text"])
            self.assertEqual(r.item("jobOk")["text"], "Replace")
            self.only_red(r)

    def test_prompt_editor(self):
        for r in self.go("promptpanel"):
            self.assertTrue(r.item("promptCard")["visible"])
            self.assertEqual(r.item("promptPanelTitle")["text"], "Prompt")
            self.assertEqual(r.item("promptNameInput")["text"], "")
            self.assertEqual(r.item("promptText")["text"], "", "a new prompt starts empty")
            self.assertEqual(r.item("promptSave")["kind"], "off", "Save is dim until something changed")
            self.assertFalse(r.item("promptDraft")["visible"])
            self.only_red(r)
        self.narrow("promptpanel")

    def test_the_default_prompt_is_read_and_copied_not_edited(self):
        for r in self.go("promptdefault"):
            self.assertEqual(r.item("promptPanelTitle")["text"], "Default prompt")
            self.assertTrue(len(r.item("promptText")["text"]) > 100, "the shipped prompt is shown")
            self.assertFalse(r.item("promptNameInput")["visible"], "no name: Default is not edited")
            self.assertEqual(r.item("promptSave")["text"], "Make a copy")
            self.assertEqual(r.item("promptSave")["kind"], "main")
            self.assertEqual(r.item("promptCancel")["text"], "Close")
            self.only_red(r)
        for r in self.go("promptcopy"):
            self.assertEqual(r.item("promptPanelTitle")["text"], "Prompt")
            self.assertEqual(r.item("promptNameInput")["text"], "Default copy")
            self.assertTrue(r.item("promptNameInput")["visible"])
            self.assertTrue(len(r.item("promptText")["text"]) > 100, "the copy starts with the Default text")
            self.assertEqual(r.item("promptSave")["kind"], "main", "a copy is ready to save")
            self.only_red(r)

    def test_a_click_below_the_prompt_text_types_at_its_end(self):
        acts = ts.base(tv("promptEdit", True), SHORT, {"op": "set", "name": "promptText", "prop": "text", "value": "abc"}, SHORT,
                       click("promptBox"), SHORT)
        r = self.go("ready", scales=(1.0,), tag="prompt_click", data_=data(), actions=acts)[0]
        self.assertTrue(r.item("promptText")["activeFocus"], "a click in the empty box puts the cursor into the text")
        self.assertEqual(r.item("promptText")["cursorPosition"], 3)

    def test_prompt_editor_with_a_draft(self):
        for r in self.go("promptdraft"):
            self.assertTrue(r.item("promptCard")["visible"])
            self.assertEqual(r.item("promptNameInput")["text"], "Literary")
            self.assertEqual(r.item("promptText")["text"], "my text {language}")
            self.assertTrue(r.item("promptDraft")["visible"])
            self.assertEqual(r.item("promptSave")["kind"], "main", "a draft is a change: Save is ready")
            self.only_red(r)

    def test_language_drop_down(self):
        for r in self.go("langdrop"):
            self.assertTrue(r.item("trLangDropCard")["visible"])
            self.assertEqual(r.item("trLangDropCard")["w"], 260)
            self.assertEqual(r.item("ddItem1")["text"], "Russian", "TUNED first")
            self.assertTrue(r.item("ddFilter")["activeFocus"])
            self.only_red(r, "trTo")

    def test_time_popover(self):
        for r in self.go("timepop"):
            self.assertTrue(r.item("timePopCard")["visible"])
            self.assertEqual(r.item("timeHeading")["text"], "Chapters 2703-2750")
            self.assertEqual([r.item("timeOption%d" % k)["text"] for k in range(3)],
                             ["1 paragraph per request", "5 paragraphs per request", "10 paragraphs per request"])
            self.assertTrue(r.item("timeUntested2")["visible"])
            self.assertFalse(r.item("timeUntested1")["visible"])
            self.assertEqual(r.item("timeOption1")["color"], BRIGHT, "the chosen one is bright")
            self.assertEqual(r.item("timeLeft")["text"], "500")
            self.assertTrue(re.fullmatch(r"\d\d:\d\d", r.item("timeRenew")["text"]))
            self.assertTrue(r.item("timeKeys")["visible"])
            self.only_red(r)

    def test_prompt_drop_down(self):
        for r in self.go("promptdrop"):
            self.assertTrue(r.item("promptDropCard")["visible"])
            self.assertEqual(r.item("promptItem0")["text"], "Default")
            self.assertEqual(r.item("promptItem1")["text"], "+ New prompt")
            self.assertFalse(r.item("promptDelete0")["visible"], "Default cannot be deleted")
            self.only_red(r)

    def test_closing_during_a_run(self):
        for r in self.go("closerun"):
            self.assertTrue(r.item("closingCard")["visible"])
            self.assertEqual(r.item("closingTitle")["text"], "Finishing the current requests")
            self.assertEqual(segs(r), ["Stopping…"], "the close stopped the run")
            self.assertEqual(r.item("trWord0")["text"], "Stopping")

    def test_closing_during_a_run_with_the_tray(self):
        for r in self.go("closeruntray"):
            self.assertTrue(r.item("closingCard")["visible"])
            self.assertEqual((r.item("closingLeft")["text"], r.item("closingMain")["text"]), ("Quit", "Hide to tray"))
            self.assertEqual(segs(r), ["Stop"], "the run goes on until the user chooses")

    def test_closing_during_a_quota_wait(self):
        for r in self.go("closewait"):
            self.assertTrue(r.item("closingCard")["visible"])
            self.assertIn("waits for the daily quota", r.item("closingText")["text"])
            self.assertRegex(r.item("closingText")["text"], r"until \d\d:\d\d")
            self.assertEqual(r.item("closingMain")["text"], "Close")
        for r in self.go("closewaittray"):
            self.assertEqual((r.item("closingLeft")["text"], r.item("closingMain")["text"]), ("Quit", "Hide to tray"))

    # ------------------------------------------------------------------------------------------------ doing things
    def test_the_header_word_opens_the_queue_while_another_series_runs(self):
        d, a = ts.SCENES["other"]
        acts = a + [click("step_translate"), SHORT]
        for r in self.go("other", tag="other_header", actions=acts):
            self.assertEqual(r.item("trTab_queue")["color"], BRIGHT, "the Queue tab is the open one")
            self.assertTrue(r.item("trQueueTab")["visible"])
            self.assertFalse(r.item("trChapterTab")["visible"])
            self.assertEqual(r.item("queueName0")["text"], "Gamma")

    def test_the_header_word_scrolls_to_the_current_chapter(self):
        d, a = ts.SCENES["running"]
        acts = [WAIT, sel("2650-2819"), WAIT, py("tr_begin", list(range(demo.position(2760), demo.position(2780)))),
                py("tr_progress", 2762, 1), click("step_translate"), SHORT]
        for r in self.go("running", tag="running_scroll", actions=acts, data_=data(demo.knights())):
            self.assertGreater(r.item("trChapterList")["contentY"], 1000, "the list moved to the current chapter")
            self.assertTrue(r.item("trTitle%d" % (demo.position(2762) - 1))["visible"] if r.has("trTitle%d" % (demo.position(2762) - 1)) else True)

    def test_choosing_the_language_from_the_pill(self):
        d, a = ts.SCENES["nolang"]
        acts = a + [click("trTo"), SHORT, click("ddItem1"), WAIT]
        r = self.go("nolang", scales=(1.0,), tag="nolang_chosen", actions=acts)[0]
        self.assertEqual(r.item("trToValue")["text"], "Russian")
        self.assertNotEqual(r.item("trToValue")["color"], RED)
        self.assertEqual(seg_color(r), BRIGHT, "Translate is ready once the language is chosen")
        self.only_red(r)

    def test_a_per_request_choice_changes_the_time(self):
        acts = ts.SCENES["timepop"][1] + [click("timeOption0"), WAIT]
        r = self.go("timepop", scales=(1.0,), tag="timepop_one", actions=acts)[0]
        self.assertFalse(r.item("timePopCard")["visible"], "the choice closes the popover")
        self.assertEqual(r.item("trTimeValue")["text"], "≈ 38 min")

    def test_the_replace_panel_cancel_starts_nothing(self):
        acts = ts.SCENES["replacepanel"][1] + [click("jobCancel"), SHORT]
        r = self.go("replacepanel", scales=(1.0,), tag="replace_cancel", actions=acts)[0]
        self.assertFalse(r.item("jobCard")["visible"])
        self.assertEqual(segs(r), ["Continue 2730-2750", "Replace job · 2800-2819"])
        self.assertEqual(r.item("step_translate")["kind"], "")

    def test_a_translated_row_opens_the_reader(self):
        d = data(demo.knights(translated=8))
        acts = ts.base(click("trTitle0"), {"op": "key", "key": "Return"}, WAIT, text="2650-2680")
        for r in self.go("ready", scales=(1.0,), tag="reader", data_=d, actions=acts):
            self.assertTrue(r.item("readerScreen")["visible"], "Enter on a translated row opens the reader")
            self.assertTrue(r.item("readerTabText")["text"].startswith("Reader"))
            self.assertFalse(r.item("translateScreen")["visible"])

    def test_the_row_menu_has_read_for_a_translated_row_only(self):
        d = data(demo.knights(translated=8))
        for tag, row, enabled in (("rowmenu", "trTitle0", True), ("rowmenu_none", "trTitle10", False)):
            acts = ts.base({"op": "click", "name": row, "button": "right"}, SHORT, text="2650-2680")
            r = self.go("ready", scales=(1.0,), tag=tag, data_=d, actions=acts)[0]
            self.assertTrue(r.item("trRowMenuCard")["visible"])
            self.assertEqual(r.item("menuItem0")["text"], "Read")
            self.assertEqual(r.item("menuItem0")["color"] == FAINT, not enabled)

    def test_a_deleted_prompt_says_so_and_can_be_brought_back(self):
        make = [tv("promptEdit", True), SHORT, tv("promptSave", "Literary", "my {language}"), SHORT]
        gone = ts.base(*make, click("trPrompt"), SHORT, click("promptDelete1"), SHORT)
        r = self.go("ready", scales=(1.0,), tag="prompt_deleted", data_=data(), actions=gone)[0]
        self.assertTrue(r.item("trUndo")["visible"])
        self.assertEqual(r.item("trUndoBarText0")["text"], "Undo")
        self.assertEqual(r.item("trUndoBarText0")["color"], BRIGHT)
        self.assertFalse(r.has("toastCard") and r.item("toastCard")["visible"], "the delete is not also a pick of the gone prompt")
        back = ts.base(*make, click("trPrompt"), SHORT, click("promptDelete1"), SHORT, click("trUndoBarText0"), SHORT,
                       click("trPrompt"), SHORT)
        r = self.go("ready", scales=(1.0,), tag="prompt_undone", data_=data(), actions=back)[0]
        self.assertFalse(r.item("trUndo")["visible"])
        self.assertEqual(r.item("promptItem1")["text"], "Literary", "Undo brought the prompt back")

    def test_prompt_editor_keeps_the_draft_on_escape_and_drops_it_on_cancel(self):
        d = data()
        typed = [tv("promptEdit", True), SHORT, {"op": "set", "name": "promptText", "prop": "text", "value": "draft text {language}"}, SHORT]
        keep = ts.base(*typed, {"op": "key", "key": "Escape"}, SHORT, tv("promptEdit", True), SHORT)
        r = self.go("ready", scales=(1.0,), tag="prompt_keep", data_=d, actions=keep)[0]
        self.assertTrue(r.item("promptCard")["visible"])
        self.assertEqual(r.item("promptText")["text"], "draft text {language}", "Esc keeps the draft for the next Edit")
        self.assertTrue(r.item("promptDraft")["visible"])
        drop = ts.base(*typed, click("promptCancel"), SHORT, tv("promptEdit", True), SHORT)
        r = self.go("ready", scales=(1.0,), tag="prompt_drop", data_=d, actions=drop)[0]
        self.assertNotEqual(r.item("promptText")["text"], "draft text {language}", "Cancel throws the draft away")
        self.assertFalse(r.item("promptDraft")["visible"])


@unittest.skipUnless(RUN, "PySide6 is not available")
class RealRun(unittest.TestCase):
    """The same screen driven by the REAL RunControl against the fake Gemini server (tests/fake_api.py) in this process: the app
    window runs in the scene's child process and reaches it through NOVELGUI_API_BASE. Every test asserts that nothing but the fake
    server was asked (the scene's service address is the only one the window has) and that the key list the server saw is ours."""

    def api(self, **kw):
        from tests import shellfactory
        from tests.fake_api import FakeApi
        api = FakeApi([shellfactory.planted(i) for i in range(2)], **kw).start()
        self.addCleanup(api.stop)
        return api

    def scene(self, api, actions, tag, scale=1.0, **kw):
        d = data(demo.knights(), keys=2, api=api.base_url, pace=120, **kw)
        d.pop("norun")
        return qh.scenario("ShellScene", d, scale=scale, vm=VM, actions=actions, tag="translate_" + tag, timeout=150)

    def only_ours(self, api):
        self.assertTrue(all(e["key"] >= 0 for e in api.log), "a request with a key the fake server does not know")

    def test_nothing_is_asked_after_the_window_opens(self):
        api = self.api()
        r = self.scene(api, ts.base(), "real_open")
        self.assertEqual(segs(r), ["Translate · 2703-2750"])
        self.assertEqual(api.log, [], "13.13: no request after the app starts")

    def test_a_job_runs_and_the_screen_follows(self):
        api = self.api(latency=1.5)
        r = self.scene(api, ts.base(tv("act", "translate"), {"op": "wait", "ms": 2600}, text="2703-2705"), "real_running")
        self.assertEqual(segs(r), ["Stop"])
        self.assertEqual(r.item("step_translate")["kind"], "wave")
        self.assertEqual(r.item("trToValue")["color"], FAINT, "To is locked while it runs")
        self.assertEqual(r.item("trSampleValue")["color"], FAINT)
        self.assertEqual(r.ambient, 1)
        self.assertGreaterEqual(len(api.log), 1, "the request went to the fake server")
        self.only_ours(api)

    def test_a_job_ends_and_the_rows_fill(self):
        api = self.api()
        r = self.scene(api, ts.base(tv("act", "translate"), {"op": "wait", "ms": 7000}, text="2703-2705"), "real_done")
        self.assertEqual([r.item("trBarFill%d" % k)["w"] for k in range(3)], [110, 110, 110])
        self.assertEqual(segs(r), ["Retranslate · 2703-2705"])
        self.assertEqual(r.item("step_translate")["kind"], "", "the wave stops with the job")
        self.assertEqual(r.ambient, 0)
        self.assertGreaterEqual(len(api.log), 3)
        self.only_ours(api)

    def test_stop_says_stopping_then_continue(self):
        api = self.api(latency=2.5)
        acts = ts.base(tv("act", "translate"), {"op": "wait", "ms": 1500}, tv("act", "stop"), {"op": "wait", "ms": 500},
                       {"op": "dump", "name": "stopping"}, {"op": "wait", "ms": 6000}, text="2703-2706")
        r = self.scene(api, acts, "real_stop")
        mid = r.after["stopping"]
        self.assertEqual(mid["trBarText0"]["text"], "Stopping…")
        self.assertEqual(mid["trWord0"]["text"], "Stopping")
        self.assertTrue(segs(r)[0].startswith("Continue"), segs(r))
        self.assertEqual(word(r, 0)[0] if word(r, 0) else "", "Stopped" if word(r, 0) else "")
        self.only_ours(api)

    def test_a_refused_key_sends_the_user_to_settings(self):
        api = self.api(invalid_keys=(0, 1))
        r = self.scene(api, ts.base(tv("act", "translate"), {"op": "wait", "ms": 7000}, text="2703-2705"), "real_key")
        self.assertEqual(segs(r)[0], "Settings")
        self.assertEqual(seg_color(r, 0), RED)
        self.assertEqual(r.item("step_translate")["kind"], "attention")
        self.assertEqual(r.item("trWord0")["text"], "Key invalid")
        self.assertEqual(r.item("trWord0")["color"], RED)
        self.only_ours(api)


if __name__ == "__main__":
    unittest.main()
