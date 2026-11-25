"""Messages that are wrong, duplicated, stale or silent (audit 1, class 5): the message queue, the saved line of Settings
(`Already there`, `No key found`), the key removed with Undo, the failed saves of the Translate screen (the shown value goes
back and one line says so), the draft of the problem editor, a late failure of something that is not open any more.
View-models only (QCoreApplication), nothing is shown."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import test_shell_vm as shell  # noqa: E402
from tests import test_translate_vm as ttv  # noqa: E402
from tests import translatedemo as demo  # noqa: E402

position = demo.position


class MessageQueue(shell.Base):
    def test_a_second_message_waits_for_the_first(self):
        vm = self.make_app({})
        seen = []
        vm.messageChanged.connect(lambda: seen.append(vm.message))
        for text in ("one", "two", "two", "one", "three", "four", "five"):
            vm.message = text
        self.assertEqual(vm.message, "one")
        self.assertEqual(vm._queued, ["two", "three", "four"], "at most three wait, the same text is not queued twice")
        vm.dismissMessage()
        self.assertEqual(vm.message, "two")
        vm.dismissMessage()
        vm.dismissMessage()
        self.assertEqual(vm.message, "four")
        vm.dismissMessage()
        self.assertEqual(vm.message, "")
        self.assertEqual(seen, ["one", "two", "three", "four", ""])

    def test_a_failure_says_plain_words_and_logs_the_exception(self):
        vm = self.make_app({})
        vm.fail("The setting could not be saved.", OSError(13, "Access is denied", "C:\\x\\settings.json"))
        self.assertEqual(vm.message, "The setting could not be saved.")
        self.assertNotIn("Access", vm.message)
        self.assertIn("Access is denied", "\n".join(e.line() for e in self.winlog.entries(False, 20)))


class SettingsLines(shell.Base):
    def setUp(self):
        super().setUp()
        self.lib = self.root / "Novel library"
        self.lib.mkdir(parents=True)
        self.app = self.make_app({"library": str(self.lib)})
        from novelgui import keystore
        from novelgui.lanes import Lanes
        from novelgui.vm.settingsvm import SettingsVM
        self.ks = keystore.KeyStore(self.data)
        self.ks.add("AIzaOnlyKey000000000000000000000001 AIzaOtherKey00000000000000000000002")
        self.lanes = Lanes()
        self.vm = SettingsVM(self.app, self.ks, self.lanes, self.local)

    def test_a_pasted_key_that_is_already_there_says_so(self):
        self.vm.addKeys("AIzaOnlyKey000000000000000000000001")
        self.assertEqual(self.vm.saved, "Already there")

    def test_a_paste_with_no_key_says_so(self):
        self.vm.addKeys("hello there")
        self.assertEqual(self.vm.saved, "No key found")

    def test_adding_a_model_that_is_in_the_list_says_so(self):
        name = self.vm._models[0]
        self.vm.addModel(name)
        self.assertEqual(self.vm.saved, "Already there")
        self.assertEqual(self.vm._models.count(name), 1)

    def test_a_removed_key_comes_back_where_it_was_and_is_never_logged(self):
        first, second = list(self.ks.keys)
        self.vm.removeKey(0)
        self.assertEqual(self.ks.keys, [second])
        self.assertNotEqual(self.vm.removedKey, "")
        self.assertNotIn(first, self.vm.removedKey, "only the masked form is shown")
        text = "\n".join(e.line() for e in self.winlog.entries(False, 50))
        self.assertNotIn(first, text)
        self.vm.undoRemoveKey()
        self.assertEqual(self.ks.keys, [first, second])
        self.assertEqual(self.vm.removedKey, "")

    def test_the_undo_ends_with_its_time(self):
        self.vm.removeKey(1)
        self.assertNotEqual(self.vm.removedKey, "")
        self.vm._undo_timer.timeout.emit()
        self.assertEqual(self.vm.removedKey, "")
        self.vm.undoRemoveKey()
        self.assertEqual(len(self.ks.keys), 1, "after the line ended the key is gone for good")


class TranslateSaves(ttv.Base):
    def test_a_failed_per_request_save_puts_the_shown_value_back(self):
        vm = self.vm
        was = vm._series["per_request"]
        other = 1 if was != 1 else 10
        with mock.patch("novelgui.facade.translate.save_per_request_task", side_effect=OSError("disk full")):
            vm.setPerRequest(other)
            self.assertEqual(vm._series["per_request"], other)
            ttv.pump(lambda: self.app.message != "")
        self.assertEqual(vm._series["per_request"], was)
        self.assertEqual(self.app.message, "The setting could not be saved.")

    def test_a_failed_choice_of_a_prompt_puts_the_name_back(self):
        vm = self.vm
        vm.promptEdit(True)
        vm.promptSave("Short", "t")
        self.settle()
        with mock.patch("novelgui.facade.books.apply_prompt", side_effect=OSError("locked")):
            vm.choosePrompt("default")
            self.assertEqual(vm.top["promptName"], "Default")
            ttv.pump(lambda: self.app.message != "")
        self.assertEqual(vm.top["promptName"], "Short")
        self.assertEqual(self.app.message, "The prompt could not be saved for this series.")

    def test_undo_of_a_deleted_prompt_gives_the_series_its_prompt_back(self):
        vm = self.vm
        vm.promptEdit(True)
        vm.promptSave("Short", "t")
        self.settle()
        vm.deletePrompt("Short")
        self.settle()
        self.assertEqual(vm.top["promptName"], "Default")
        vm.undoPromptDelete()
        self.settle()
        self.assertEqual(vm.top["promptName"], "Short")

    def test_a_failed_undo_of_a_deleted_prompt_says_so(self):
        vm = self.vm
        vm.promptEdit(True)
        vm.promptSave("Short", "t")
        vm.deletePrompt("Short")
        with mock.patch.object(vm.prompts, "save", side_effect=OSError("locked")):
            vm.undoPromptDelete()
        self.assertEqual(self.app.message, "The prompt could not be put back.")

    def test_enter_on_an_untranslated_chapter_says_why(self):
        self.vm.readRow(0)
        from novelgui import tips
        self.assertEqual(self.app.message, tips.READ_OFF)


class ProblemDrafts(ttv.Base):
    specs = [demo.knights(translated=0)]

    def prepare(self):
        demo.write_failed_block(self.path, "Book 1", position(2710), 1)
        demo.write_failed_block(self.path, "Book 1", position(2720), 0, "refused")

    def setUp(self):
        super().setUp()
        self.vm._load_problems()
        ttv.pump(lambda: len(self.vm._problems) == 2)
        self.settle()
        self.vm.setTab("problems")

    def test_a_failed_save_says_one_line(self):
        vm = self.vm
        vm.selectProblem(0)
        with mock.patch("novelgui.facade.checks.resolve_problems_task", side_effect=OSError("locked")):
            vm.saveProblem("typed")
            ttv.pump(lambda: self.app.message != "")
        self.assertEqual(self.app.message, "The block could not be saved.")

    def test_what_is_typed_is_kept_per_row(self):
        vm = self.vm
        vm.selectProblem(0)
        vm.problemDraft("first draft")
        vm.selectProblem(1)
        self.assertEqual(vm.editor["text"], "", "another row has its own text")
        vm.problemDraft("second draft")
        vm.selectProblem(0)
        self.assertEqual(vm.editor["text"], "first draft")
        vm.selectProblem(1)
        self.assertEqual(vm.editor["text"], "second draft")

    def test_a_reload_keeps_the_open_row_and_its_draft(self):
        vm = self.vm
        vm.selectProblem(1)
        vm.problemDraft("typed")
        vm._load_problems()
        ttv.pump(lambda: False, 0.5)
        self.settle()
        self.assertTrue(vm.editor["open"], "the editor of a row that still exists stays open")
        self.assertEqual(vm.editor["index"], 1)
        self.assertEqual(vm.editor["text"], "typed")


class StaleFailures(ttv.Base):
    def test_a_late_failure_of_a_book_that_is_not_open_is_logged_not_shown(self):
        self.app.message = ""
        self.books._on_failed("scan", OSError("gone"), ("C:/elsewhere", "Old book"))
        self.assertEqual(self.app.message, "")
        self.books._on_failed("scan", OSError("gone"), (self.books.session.series_path, self.books.session.book))
        self.assertEqual(self.app.message, "The book could not be read.")

    def test_a_terms_scan_failure_of_another_book_is_not_shown(self):
        self.app.message = ""
        self.terms._scan_failed(OSError("gone"), ("C:/elsewhere", "Old book"))
        self.assertEqual(self.app.message, "")


if __name__ == "__main__":
    unittest.main()
