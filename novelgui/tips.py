"""Tooltip texts added in stage 3, in one place. A text is a plain explanation; the caller adds the list of
`name  value` facts (see tooltip.py)."""

from __future__ import annotations

# Terms: the dim dash of an empty type / gender / About
UNKNOWN_FIELD = ("Not known yet. A later pass of the model fills it in, or you can write it yourself.",
                 [("Filled by", "the model, or you"), ("You can edit", "yes")])

# Terms: the toggle that narrows the list to the chapters chosen on Books
SELECTED_CHAPTERS = "Show only the terms that occur in the chapters selected on the Books step."

# Settings: the label of the keep-awake row
KEEP_AWAKE_LABEL = "Keep the computer awake while translating"

# Books: actions of a series row and of a volume
SERIES_ACTIONS = ("Actions for this series: rename it, open its folder, delete it.",
                  [("Rename", "changes the shown name only"), ("Delete", "moves it to .deleted")])
VOLUME_ACTIONS = ("Actions for this volume: rename it or remove it from the series.",
                  [("Rename", "changes the shown label only"), ("Remove", "moves its files to .deleted")])
BROKEN_SERIES = "This series cannot be opened: %s."

# Add book panel
ADD_VOLUME_OF = ("The file becomes another book of this series. The glossary, the language and the settings "
                 "of the series are shared by all its books.",
                 [("Copies the file", "into the series folder"), ("Original", "stays where it is")])
ADD_NEW_SERIES = ("A separate series with its own glossary, language and settings. The file is copied into it.",
                  [("Copies the file", "into the new folder"), ("Original", "stays where it is")])
ADD_SERIES_NAME = ("The name of the series as the list shows it. Its folder in the library is named after it.",
                   [("Must be", "unused in the library")])
ADD_SERIES_NAME_FIXED = "The name of the series this volume goes to. Change it with Rename in the series menu."

# Settings: the library row
ADDING = "A book is being copied into the library. Add book is back when it is done."
TERMS_IMPORTING = ("The glossary is being read and the open book is scanned for the imported terms, to fill Count "
                   "and the chapters. You can look around; editing waits until it is done.",
                   [("Then", "Count and chapters are filled")])
TERMS_SCANNING = ("The book is being read to find where the terms occur. The table stays usable; the Next filter "
                  "fills in when this is done.", [("Shown as", "percent of the book read")])
TERMS_NO_MATCH = "No term matches the search text (and the type chosen)."
KEYS_LIST =("Your API keys, each with its state: ready, paused until a time, daily quota until a time, or invalid "
             "(the service refused it). A key from a separate Google project brings its own daily quota. A key is "
             "never shown in full. A key added or removed while a translation runs applies from the next start.",
             [("Stored in", "keys.json"), ("State", "worst over all series"), ("Never", "in a series or a log")])
LIBRARY_PATH =("The folder that holds every series. Click to open it.",
                [("Kept in", "this app's settings"), ("Series", "one sub-folder each")])
LIBRARY_CHANGE = ("Choose another folder for the library. Series in the old folder are not moved.",
                  [("Needs", "no running translation")])

# Deleting and removing: why it is not possible now
CANNOT_NOW = "%s Try again when it has ended."

# Books: the typed range
CHAPTERS_FIELD = ("Type chapter numbers as they are printed in the titles, for example 2729-2783 or 5, 9-12, and "
                  "press Enter. A number the book does not have is left out; when no title carries a number "
                  "in the range, the numbers are taken as the No. of the list.",
                  [("Format", "a-b, or a, b, c-d"), ("Counts", "title numbers"), ("Fallback", "position")])

# First start
FIRST_START_PATH = ("The folder that will hold every series, with its books and translations. A new folder is "
                    "created; a folder that already holds series is used as it is.",
                    [("Default", "Novel library, in Documents"), ("Kept in", "this app's settings")])
FIRST_START_CREATE = "Use this folder as the library."

# Languages (window 3.x)
TO_EMPTY = ("Choose the language this series is translated into. Run, Sample and the terms need it.",
            [("Applies to", "this series"), ("Changes", "until a block is translated or a term is confirmed")])
TO_CHOSEN = ("The language this series is translated into. The prompt and the terms use it.",
             [("Applies to", "this series"), ("Changes", "until a block is translated or a term is confirmed")])
TO_BUSY = "The language is read when a translation starts. %s Change it after it has ended."
TO_OTHER_FIELD = ("The language as tag:Name. The tag is its short code, the name is how the translator is told to "
                  "call it.", [("Format", "tag:Name"), ("Example", "de:German"), ("Tag", "two or three letters")])
NEED_LANGUAGE = "Choose the language first: To, next to Prompt on the Translate step, or the column heading here."
TERMS_TO_HEAD = ("The language the terms are translated into. Choose it here or on the Translate step; the "
                 "renderings in this column depend on it.",
                 [("Applies to", "this series"), ("Same setting as", "To on Translate")])
SERIES_NO_LANGUAGE = "No language chosen yet. Choose it with To on the Translate step."

# Header: the path and the context line (window 1.1-1.4)
PATH_BOOKS = ("Choose the series, the volume and the chapters to work on.", [("Step", "1 of 4")])
PATH_TERMS = ("Check the names and terms of the chosen chapters before translating.",
              [("Step", "2 of 4"), ("Number", "terms still to review")])
PATH_TERMS_N = ("%d terms of the chosen chapters are not reviewed yet. %s",
                [("Step", "2 of 4"), ("Number", "terms still to review")])
PATH_TERMS_RED = "Translation cannot start: the first chosen chapter has terms to review."
PATH_TERMS_DIM = "Translation can start; the later chapters stop at the first one that has terms to review."
PATH_TRANSLATE = ("Run the translation of the chosen chapters.", [("Step", "3 of 4")])
PATH_EXPORT = ("Write the translated chapters of the volume into an EPUB file.", [("Step", "4 of 4")])
CONTEXT_LINE = ("What the next steps work on: series, volume, chosen chapters and the language. Click to go to "
                "Books and change it.", [("Chapters", "numbers from the titles"), ("Click", "opens Books")])

# Export (window 8)
EXPORT_PIECE = ("Chapters that are translated one after another. Click to put its range into the fields below.",
                [("Counts", "fully translated chapters"), ("Updated", "while a translation runs")])
EXPORT_PROBLEM = ("Some blocks of these chapters failed. The chapters with failed blocks are left out of the "
                  "file until they are solved. Click to see them on Translate.",
                  [("Opens", "Translate"), ("Left out", "chapters with failed blocks")])
EXPORT_FROM = ("The first chapter of the file, as the number printed in its title (the position when a title has "
               "no number). Only fully translated chapters between the two numbers are written.",
               [("Format", "a number"), ("Default", "the piece you click")])
EXPORT_TO = ("The last chapter of the file, as the number printed in its title. Only fully translated chapters "
             "between the two numbers are written.", [("Format", "a number"), ("Default", "the piece you click")])
EXPORT_SINGLE = ("Write the translation only: the original text is replaced. The file goes to the out folder of "
                 "the series; an existing file is never overwritten.",
                 [("Folder", "out, in the series"), ("Name", "series, chapters, language")])
EXPORT_BILINGUAL = ("Write each original paragraph with its translation next to it. The file goes to the out "
                    "folder of the series; an existing file is never overwritten.",
                    [("Folder", "out, in the series"), ("Name", "series, chapters, languages")])
EXPORT_NEED_PAIR = "Type a range that has fully translated chapters, or click a piece in the list."
EXPORT_RUNNING = "An export of this volume is in progress."
EXPORT_LAST = ("The file written last. Click to show it in its folder.", [("Folder", "out, in the series")])
EXPORT_LEFT_OUT = ("Chapters of the range that are not fully translated yet are not in the file: %s.",
                   [("Left out", "not fully translated")])

# Translate: the top row (window 7.1, 7.12, 13.1)
PER_REQUEST = ("How many blocks travel in one request. More blocks per request mean fewer requests of the daily "
               "quota; every block is checked on its own either way.",
               [("Choices", "1, 5 or 10"), ("Applies to", "this series"), ("Changes", "at once")])
PER_REQUEST_LOCKED = ("Blocks per request is read when a translation starts. While this series is translated it "
                      "cannot change; the new value applies from the next start (Stop, then Continue).",
                      [("Applies from", "the next start"), ("Now", "locked")])
PROMPT_LIVE = ("The instructions the translator gets with every request. A prompt saved while a translation runs "
               "applies from the next chapter.", [("Applies to", "this series"), ("Saved in", "the series folder")])

# Translate: zone 2, the start button (window 7.3)
START_TRANSLATE = ("Translate the chosen chapters in order. It stops at the first chapter with terms that are not "
                   "reviewed yet.", [("Chapters", "%s"), ("Starts", "now")])
START_QUEUE = ("Another translation is running, so these chapters wait in the queue and start when it ends. "
               "The prompt, blocks per request and language are the series' values at that moment.",
               [("Chapters", "%s"), ("Starts", "after the running job")])
START_QUEUE_QUOTA = ("The daily quota of the keys is used up until %s. A new job would only meet it, so these "
                     "chapters wait in the queue.", [("Quota returns", "%s"), ("Chapters", "%s")])
START_REPLACE = ("This series has an unfinished job on other chapters. Starting these chapters replaces it; "
                 "translated chapters are kept.", [("Chapters", "%s"), ("Replaces", "the unfinished job")])
START_QUEUE_REPLACE = ("This series has an unfinished job on other chapters and another job runs. These chapters "
                       "wait in the queue and replace the unfinished job when they start; translated chapters "
                       "are kept.", [("Chapters", "%s"), ("Replaces", "the unfinished job")])
START_DONE = "Every block of the chosen chapters is translated already."
START_SAMPLE_RUNS = "A sample is being translated. Start after it has ended."
START_ELSEWHERE = "Another program is working on this series. Wait for it to finish."
START_NEED_SELECTION = "Choose chapters on the Books step first."
ADD_KEYS = "Add an API key in the settings to translate."
REVIEW_TERMS = ("Chapters are translated only up to the first one with terms that are not reviewed. Open the Terms "
                "step on these terms.", [("Opens", "Terms, Next"), ("Terms", "%d")])

# Translate: zone 1, the job of this series (window 7.6, 7.7)
Z1_STOP = ("Finish the requests in flight, record them and stop. Nothing is lost; Continue picks up where it "
           "stopped. A waiting queue stops too.", [("Saved", "every finished block")])
Z1_CONTINUE = ("Continue the unfinished job: same book, same chapters. Translated blocks are skipped.",
               [("Chapters", "%s"), ("Done", "%s")])
Z1_QUEUE_CONTINUE = ("Another translation is running. This job continues after it, from the queue.",
                     [("Chapters", "%s"), ("Starts", "after the running job")])
Z1_WAIT_QUOTA = ("The daily quota of every key is used up. The job continues after the quota returns%s.",
                 [("Returns at", "%s"), ("Saved", "yes")])
Z1_WAIT_QUOTA_AUTO = " by itself while this window stays open"
Z1_WAIT_TERMS = ("Chapters are translated only when every term in them is reviewed. Review the terms, then "
                 "continue.", [("Next step", "Terms")])
Z1_STOP_WAIT = ("Cancel the automatic continue. The job becomes stopped and the queue stops; Continue starts it "
                "by hand.", [("Job", "stopped")])
Z1_SETTINGS = ("The key or the model was refused. Fix it in the settings; Continue then tries again.",
               [("Opens", "Settings")])
Z1_MORE = ("Actions for this job.", [("Discard job", "forget the unfinished job, keep the translated chapters")])
Z1_DISCARD_CONFIRM = ("Discard the unfinished job of %s? Chapters that are translated stay translated; the job "
                      "record is closed and Continue is gone.")
Z1_NO_KEYS = "Add an API key in the settings to continue."
Z1_ELSEWHERE = "Another program is working on this series. Wait for it to finish."
CHIP_FAILED = ("%s. Fix the cause, then Continue tries again.", [("Next", "Continue")])
CHIP_RETRYING = ("A request failed and is being repeated after a pause. It goes on by itself.", [("Next", "automatic")])

# Translate: the queue (window 7.5)
QUEUE_RUNNING = ("The translation that runs now. Stop ends it and stops the queue.", [("Series", "%s")])
QUEUE_ITEM = ("Starts when the running job ends, with the series' own prompt, blocks per request and language at "
              "that moment.", [("Prompt", "%s"), ("Per request", "%s"), ("Language", "%s")])
QUEUE_REMOVE = "Remove this item from the queue. Nothing of the series changes."
QUEUE_MORE = ("Move this item up or down the queue.", [("Order", "first runs first")])
QUEUE_CONTINUE = ("Start the queue from its first item. Nothing starts by itself after the program was opened or a "
                  "translation was stopped.", [("Starts", "the first item")])
QUEUE_STATE = "%s"
QUEUE_REPLACE_CONFIRM = ("%s is queued already. Replace its item with the new chapters?")

# Header: the Translate indicator (window 1.2, 11.5)
IND_RUNNING = ("The running translation. Click to open its series on the Translate step.",
               [("Series", "%s"), ("Volume", "%s"), ("Chapters", "%s"), ("Model", "%s"), ("Keys", "%s"),
                ("Pace", "%s")])
IND_WAIT = ("The daily quota of every key is used up. The job continues after it returns.",
            [("Returns at", "%s"), ("Series", "%s")])
IND_TERMS = ("The job stopped at a chapter whose terms are not reviewed. Click to open its series.",
             [("Series", "%s"), ("Next step", "Terms")])
IND_STOPPED = ("The translation is stopped. Click to open its series; Continue picks up where it stopped.",
               [("Series", "%s")])
IND_FAILED = ("The translation stopped on an error. Click to open its series.", [("Series", "%s")])
IND_QUEUE = ("Items wait in the queue. Nothing starts by itself after the program was opened.",
             [("Queued", "%s")])

# Sample (window 7.13)
SAMPLE = ("Translate the first blocks of the first chosen chapter to see how it reads. Nothing is added to the "
          "book.", [("Blocks", "the number on the right"), ("Uses", "requests of today"), ("Saved", "no")])
SAMPLE_UNREVIEWED = ("Terms of this chapter are not reviewed yet, so names and terms in the sample may differ from "
                     "the real translation.", [("Unreviewed", "%d"), ("Uses", "requests of today")])
SAMPLE_BUSY = "A translation runs or waits for the daily quota. A sample uses the same keys; try after it."
SAMPLE_STOP = "Stop the sample. Nothing of it is part of the book."

# One app window (window 10.9)
ALREADY_OPEN = "Novel is already open. It was brought to the front."


def fill(tip, *values):
    """A tooltip whose `%s` / `%d` marks (in the text first, then in the fact values, in order) are replaced by
    `values`. A plain string or a two-part tuple both work."""
    import re
    vals = list(values)
    mark = re.compile(r"%[sd]")

    def sub(s):
        return mark.sub(lambda m: str(vals.pop(0)) if vals else "", s)
    if isinstance(tip, str):
        return sub(tip)
    text, facts = tip
    text = sub(text)
    return text, [(name, sub(v)) for name, v in facts]


# ---------------------------------------------------------------- the shell of the QML window (step 4)
TITLE_MIN, TITLE_MAX, TITLE_RESTORE, TITLE_CLOSE = "Minimize", "Maximize", "Restore", "Close"
GEAR = "Settings: keys, models, pace, library."
FIRST_START_FOLDER = ("Series, translations and glossaries are kept here. Any folder works; Settings can change it "
                      "later.", [("Default", "Novel library"), ("Kept in", "this app's settings")])
LIBRARY_NOT_FOUND_FOLDER = "Choose the folder that holds your series."
KEYS_HEAD = ("Free Gemini API keys, one per Google project. Changes apply from the next start of a job.",
             [("Stored in", "the app data folder"), ("Shown as", "dots and the last 4 characters")])
KEYS_PLUS = ("Add keys", [("Get a free key at", "aistudio.google.com/apikey")])
KEY_INVALID = "Google does not accept this key. It may be copied incompletely, or switched off in Google AI Studio."
KEY_NO_ACCESS = "Google's API is not available from your location for this key."
KEY_NO_CONNECTION = "Cannot reach Google. Check the internet connection and the proxy settings."
MODELS_HEAD = ("Tried in this order: the first model is used while any key has requests for it; the next one only "
               "when none has. Changes apply from the next start of a job.")
MODELS_PLUS = "Add a model"
MODEL_NOT_FOUND = "Google does not know this model name. A job with it stops until the name is changed."
MODEL_RECOMMENDED = "Tested with this app; the daily limit per key is known."
MODEL_FROM_GOOGLE = ("The current list from Google, read once a day with one of your keys. Offline: only "
                     "Recommended.")
MODEL_GOOGLE_ITEM = "Listed by Google. Its free limits are not known to the app; some models have none."
PACE_ROW = ("How often the app sends a request. One request at a time, evenly spaced: 5 = one every 12 s, never "
            "several at once. The keys take turns. More keys give more requests per day, not more speed: Google "
            "counts this limit for the whole PC. Above 5, Google may pause every key of this PC for minutes.",
            [("Range", "1 to 120"), ("Default", "5")])
AWAKE_ROW = "The PC does not sleep while a job runs or waits in the open window for the daily quota."
AWAKE_ROW_OFF = "Not available on this system yet"
LIBRARY_ROW_CHANGE_BUSY = "A job is running. Change the library when it stops."
APP_DATA_ROW = ("The program's own data: databases, backups, terms snapshots, the trash and the logs. Uninstalling "
                "the program does not delete this folder; delete it by hand if you want it gone. The library is "
                "never touched.", [("Click", "opens the folder")])
GRAPHICS_ROW = ("Auto uses the graphics card. Software draws on the processor: slower, but safe when the window "
                "stays empty or flickers. Applies from the next start.")
LOG_BUTTON = "The log of this window: what it did and every problem, without keys."

# Books v6 (step 5)
ADD_BOOK_PLUS = "Add book"
CHAPTERS_HEAD = ("Select all chapters, or none. Type numbers on the list to select a range.", [])
CHAPTER_STATE = ("How much of the chapter is translated.", [("Full line", "every block is translated")])
NEXT_STEP = ("The next step for this selection. It only opens the step; nothing starts.", [])
MOVE_OFF = "Only a book with nothing translated can move: the glossary and the language belong to its series."
UPDATE_FILE_OFF = "Comes with a later program change."
READ_OFF = "Nothing of this chapter is translated yet."
RENAME_TAKEN = "Another series already has this name."
UNDO = "Brings it back from the program's trash, with its books, translations and glossary."


# ---------------------------------------------------------------- Translate v9 (window 7.16, 14.15)
TR_WORDS = {
    "stopped": "The job stopped here. Continue goes on from this chapter.",
    "key": "Google says a key is invalid. Fix it in Settings, then Continue.",
    "model": "Google does not know the model name. Fix it in Settings, then Continue.",
    "nopair": "No key and model pair can be used any more. Check them in Settings, then Continue.",
    "disk": "The disk is full or a file cannot be written. Free some space, then Continue.",
    "service": "The service kept failing. Continue later.",
    "shut": "Google refused every request for half an hour. Continue later.",
    "crash": "The job stopped on an error. `Copy details` in the ••• menu has the text; then Continue.",
    "resumes": "Today's requests of all keys are used. The job goes on here at %s if the window stays open.",
    "retrying": "A request failed (server busy, lost connection) and is repeated. Nothing to do.",
    "paused": "Google refused for going too fast. All keys wait, then the job goes on by itself.",
    "stopping": "Finishing the requests already sent (up to a minute), then the job stops here.",
    "terms": "%d of this chapter's terms are not confirmed yet. Click: Terms on Blocking.",
    "busy": "Another copy of the program, or its command line, is translating on this PC. One translation at a time.",
    "problems": "Blocks that failed or that a check flagged. Click: the Problems tab.",
}
TR_TO_LOCKED_RUN = "The language is fixed while this series translates."
TR_FROM = "The language of the book. Reserved: it is read from the file."
TR_PROMPT = "How the model is asked to translate. Choose another or make a new one."
TR_PROMPT_EDIT = "Edit the prompt %s. A saved prompt applies from the next chapter, also during a run."
TR_PROMPT_DELETE = "Delete this prompt. The series that use it go back to Default."
TR_SAMPLE = ("Translates the first %d blocks of the first selected chapter to try the prompt. The result opens in the "
             "Sample tab; it is not saved as translation.")
TR_SAMPLE_RUNNING = "Translating a sample: %d of %d blocks. Click: stop it."
TR_SAMPLE_UNREVIEWED = ("Names and terms in this sample may differ from the real translation: %d terms of this chapter "
                        "are not reviewed.")
TR_SAMPLE_OFF = {"running": "A job is running or waiting: one at a time.", "keys": "Add keys first.",
                 "language": "Choose the language first.", "selection": "Select chapters on Books first."}
TR_TIME = "About how long chapters %s take. Click: paragraphs per request."
TR_TIME_RUNNING = "Time left for this job. Paragraphs per request apply from the next start."
TR_TIME_LOCKED = "Locked while this series translates: Stop, then Continue uses the new choice."
TR_PER = {1: "One paragraph per request: the slowest, the most requests.",
          5: "About 1000 characters, 10 paragraphs at most. No loss of quality was measured against 1.",
          10: "About 2000 characters, 20 paragraphs at most. Not yet compared with 1 and 5 for quality."}
TR_KEYS_HEAD = "Your Google API keys. Click: Settings at the keys."
TR_LEFT = "All keys together: %s, 500 requests a day each."
TR_TAB = {"chapters": "The chapters of the selection.", "problems": "Blocks that failed or that a check flagged.",
          "queue": "Jobs that wait for their turn.", "sample": "The sample of the first chapter."}
TR_TAB_RED = "%d blocks failed: they are left out of export until fixed."
TR_START_WAIT = "Waiting for the name scan of the book: it decides which chapters can be translated now."
TR_START_NEED_LANGUAGE = "Choose the language to translate into (To) first."
TR_BAR = {"stop": "Finishes the requests in flight, then stops. Stops the queue too.",
          "dont_resume": "The job will not go on by itself at %s. It stays stopped; Continue it later.",
          "settings": "The key or the model was refused. Fix it in Settings; Continue then tries again.",
          "open_folder": "Opens the series folder: free some space, then Continue.",
          "more": "Job actions.", "continue_queue": "Starts the saved queue.",
          "check": "Looks for leftover source language, odd lengths, terms not used and broken markup in the selected "
                   "chapters. Never changes text.",
          "stopping": "Finishing the requests already sent, then the job stops."}
TR_CONTINUE = "Continue the job %s from the chapter it stopped at. Translated blocks are skipped."
TR_CONTINUE_AFTER = "%s is translating. This goes into the queue and continues %s when it ends."
TR_CONTINUE_KEYS = "Add an API key in the settings to continue."
TR_PROBLEM = {"retry": "Translate this block again (it goes through the start rules: queued if a job runs).",
              "keep": "Keep the source text in the translation.",
              "ignore": "Hide this finding for good. The text stays as it is.",
              "save": "Use the text you typed as the translation of this block.",
              "failed": "The model gave no usable answer for this block.",
              "busy": "A job is translating this chapter now. Resolve it when the job ends."}
TR_QUEUE_ROW = "Prompt %s · %s per request · %s.\nClick: open %s on Translate."
TR_QUEUE_UP, TR_QUEUE_DOWN, TR_QUEUE_X = "Move up", "Move down", "Remove from the queue"
TR_QUEUE_STOP = "Finishes the requests in flight, then stops. The queue waits."
TR_QUEUE_WHY = "%s Click: Translate of %s."
TR_NO_SERIES = "No book selected"
