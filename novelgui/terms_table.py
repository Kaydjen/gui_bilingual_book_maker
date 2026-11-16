"""The term table: cells drawn on the virtual list, inline editing, choice lists for type / gender / questions."""

from __future__ import annotations

import tkinter as tk

from . import termlogic, termtips, tips
from .chapterlogic import display_no
from .terms_const import FIELD_OF, OTHER, QUESTION_COL, TYPES
from .theme import ACCENT, BRIGHT, DIM, FAINT, S2, S4, TEXT
from .vtable import Col, VTable

DASH = "—"
EDITABLE = ["tr", "type", "gender", "note"]
GENDER_ORDER = ["male", "female", "neuter", "plural", "unknown"]


def empty_type(t) -> bool:
    return not (t.type or "").strip()


def empty_gender(t) -> bool:
    return (t.gender or "") in ("", "unknown")


def empty_note(t) -> bool:
    return not (t.note or "").strip()


class TermsTable(VTable):
    def __init__(self, master, ui, target_name: str, marks: dict):
        cols = [Col("source", "Source", 26), Col("tr", target_name, 28), Col("type", "Type", 13),
                Col("gender", "Gender", 9), Col("first", "First", 8, "e"), Col("count", "Count", 8, "e"),
                Col("note", "About", None)]
        super().__init__(master, ui, cols)
        self.marks = marks
        self.on_edited = None          # (entry) after a value changed
        self.apply = None              # (entry, field, value) -> bool: store a value, True when it changed
        self.edit = None
        self.sort_key = "count"
        self.sort_desc = True

    # ---- cells
    def draw_cells(self, c, t, cols, y, mid):
        f = self.font
        cand = getattr(t, "cand", False)
        x, w = cols["source"]
        s = self.fit(t.source, w - 2 * self.pad)
        c.create_text(x + self.pad, y + mid, text=s, anchor="w", font=f,
                      fill=DIM if getattr(t, "suggest", False) else TEXT)
        used = f.measure(s)
        if "same_as" in t.questions:
            c.create_text(x + self.pad + used, y + mid, text=" ?", anchor="w", font=f, fill=ACCENT)
            used += f.measure(" ?")
        if t.forms:
            used += self.cw
            room = w - 2 * self.pad - used
            if room > self.cw * 4:
                c.create_text(x + self.pad + used, y + mid, text=self.fit("= " + ", ".join(t.forms), room),
                              anchor="w", font=f, fill=FAINT)
        x, w = cols["tr"]
        if "tr" in t.questions:
            self._draw_question(c, x, y + mid, w, t.tr, BRIGHT)
        else:
            c.create_text(x + self.pad, y + mid, text=self.fit(t.tr, w - 2 * self.pad), anchor="w", font=f,
                          fill=BRIGHT)
        x, w = cols["type"]
        if not cand:
            if empty_type(t):
                self._draw_dash(c, x, y + mid)
            else:
                c.create_text(x + self.pad, y + mid, text=t.type, anchor="w", font=f, fill=DIM)
        x, w = cols["gender"]
        mark = self.marks.get(t.gender, "?")
        if cand:
            pass
        elif "gender" in t.questions:
            self._draw_question(c, x, y + mid, w, mark, DIM)
        elif empty_gender(t):
            self._draw_dash(c, x, y + mid)
        else:
            c.create_text(x + self.pad, y + mid, text=mark, anchor="w", font=f, fill=DIM)
        x, w = cols["first"]
        fs = termlogic.first_seen(t)
        if fs is not None:
            c.create_text(x + w - self.pad, y + mid, text=str(display_no(fs)), anchor="e", font=f, fill=DIM)
        x, w = cols["count"]
        c.create_text(x + w - self.pad, y + mid, text=str(t.count), anchor="e", font=f, fill=DIM if t.count else FAINT)
        x, w = cols["note"]
        if empty_note(t) and not cand:
            self._draw_dash(c, x, y + mid)
        else:
            c.create_text(x + self.pad, y + mid, text=self.fit(t.note or "", w - 2 * self.pad), anchor="w", font=f,
                          fill=FAINT)

    def _draw_dash(self, c, x, ymid):
        """A value that is not known yet: a dim dash (its tooltip says who fills it in)."""
        c.create_text(x + self.pad, ymid, text=DASH, anchor="w", font=self.font, fill=FAINT)

    def _draw_question(self, c, x, ymid, w, shown, fg):
        """Doubtful value: the value in use followed by an accent '?'."""
        f = self.font
        avail = w - 2 * self.pad
        q = f.measure(" ?")
        s = self.fit(shown, max(self.cw * 2, avail - q)) if shown else ""
        x0 = x + self.pad
        if s:
            c.create_text(x0, ymid, text=s, anchor="w", font=f, fill=fg)
        c.create_text(x0 + f.measure(s), ymid, text=" ?" if s else "?", anchor="w", font=f, fill=ACCENT)

    # ---- tooltips
    def tip_body(self, e):
        if self.edit or self.ui.popup.open:
            return None
        i = self.row_at(e.y)
        col = self.col_at(e.x)
        if i is None:
            return None
        t = self.rows[i]
        field = FIELD_OF.get(col)
        if col in QUESTION_COL.values():
            qf = next((f for f, c in QUESTION_COL.items() if c == col), None)
            if qf in t.questions:
                return termtips.question_tip(t, qf, self.marks)
        if not getattr(t, "cand", False) and (
                (col == "type" and empty_type(t)) or
                (col == "gender" and empty_gender(t) and "gender" not in t.questions) or
                (col == "note" and empty_note(t))):
            return tips.UNKNOWN_FIELD
        if col == "gender":
            word = termtips.GENDER_WORDS.get(t.gender, t.gender)
            return "%s: %s" % (self.marks.get(t.gender, "?"), word)
        if col == "source" and t.forms:
            return "%s\nalso: %s" % (t.source, ", ".join(t.forms))
        if col in ("source", "tr", "note"):
            val = getattr(t, "source" if col == "source" else col)
            w = self.col_x()[col][1] - 2 * self.pad
            if val and self.fit(val, w) != val:
                return val
        if col == "first":
            fs = termlogic.first_seen(t)
            if fs is not None:
                return "First found in chapter %d; found in %d chapters." % (display_no(fs), len(t.seen))
        return None

    def tip_head(self, e):
        return termtips.head_tip(self.col_at(e.x))

    def copy_text(self, rows) -> str:
        return "\n".join("%s\t%s" % (t.source, t.tr) for t in rows)

    # ---- clicks
    def after_click(self, e, i, ctrl, shift):
        if ctrl or shift:
            return
        col = self.col_at(e.x)
        qf = next((f for f, c in QUESTION_COL.items() if c == col), None)
        if qf and qf in self.rows[i].questions:
            self.start_edit(i, col)

    def before_click(self, i):
        self.close_edit(commit=True)

    def _activate(self):
        if self.cursor is not None:
            col = self.last_col if self.last_col in EDITABLE else "tr"
            q = self.rows[self.cursor].questions
            if q:
                wanted = QUESTION_COL.get("gender" if "gender" in q else next(iter(q)))
                if col not in [QUESTION_COL[f] for f in q]:
                    col = wanted
            self.start_edit(self.cursor, col)
        return "break"

    def _dbl(self, e):
        i = self.row_at(e.y)
        col = self.col_at(e.x)
        if i is not None and (col in EDITABLE):
            self.start_edit(i, col)
        return "break"

    # ---- editing
    def cell_rect(self, i, col):
        x, w = self.col_x()[col]
        return x, i * self.rh - self.y0, w, self.rh

    def start_edit(self, i, col, bypass=False):
        term = self.rows[i] if 0 <= i < len(self.rows) else None
        self.close_edit(commit=True)
        if term is not None:
            i = self.index_of(term)
        qf = next((f for f, c in QUESTION_COL.items() if c == col), None)
        question = bool(term is not None and qf in term.questions and not bypass)
        if i is None or not (0 <= i < len(self.rows)) or not (col in EDITABLE or question or bypass):
            return
        self.last_col = col
        if self.sel != {i}:
            self.sel, self.cursor, self.anchor = {i}, i, i
            self._fire()
        self.ensure_visible(i)
        self.draw()
        t = self.rows[i]
        x, y, w, h = self.cell_rect(i, col)
        holder = tk.Frame(self.body, bg="#4a4a4a")
        inner = tk.Frame(holder, bg=S2)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.edit = {"i": i, "col": col, "term": t, "holder": holder, "closing": False}
        if (col in ("tr", "note") and not question) or (bypass and col in ("tr", "source")):
            ent = tk.Entry(inner, font=self.font, bd=0, relief="flat", bg=S2, fg=BRIGHT, insertbackground=BRIGHT,
                           insertwidth=2, selectbackground=S4, selectforeground=BRIGHT, highlightthickness=0)
            ent.pack(fill="both", expand=True, padx=self.pad - 1)
            ent.insert(0, getattr(t, "same_as" if col == "source" else col))
            ent.select_range(0, "end")
            holder.place(x=x, y=y, width=w, height=h)
            ent.focus_set()
            ent.bind("<Return>", lambda e: self._entry_done("down"))
            ent.bind("<Escape>", lambda e: self.close_edit(commit=False, refocus=True))
            ent.bind("<Tab>", lambda e: self._entry_done("next") or "break")
            ent.bind("<Shift-Tab>", lambda e: self._entry_done("prev") or "break")
            ent.bind("<FocusOut>", lambda e: self.after(30, self._entry_blur))
            self.edit["entry"] = ent
            return
        shown = self._shown(t, col)
        lab = tk.Label(inner, text=self._shown_label(t, col), font=self.font, bg=S2, fg=BRIGHT, anchor="w")
        lab.pack(fill="both", expand=True, padx=self.pad - 1)
        holder.place(x=x, y=y, width=w, height=h)
        labels = hints = None
        pw = max(w, self.cw * (24 if col == "gender" else 14))
        if col == "type":
            items = list(TYPES)
        elif col == "gender":
            items = list(GENDER_ORDER)
            labels = {g: "%s  %s" % (self.marks.get(g, "?"), termtips.GENDER_WORDS.get(g, g)) for g in GENDER_ORDER}
            if question:
                cands = [c["value"] for c in t.questions["gender"]]
                items = cands + [g for g in GENDER_ORDER if g not in cands]
                hints = {c["value"]: c.get("evidence", "") for c in t.questions["gender"]}
                pw = self.cw * 40
        else:        # a doubtful rendering or alias
            cands = [c["value"] for c in t.questions.get(qf, [])]
            items = cands + [OTHER]
            labels = {OTHER: "Other…"}
            hints = {c["value"]: c.get("evidence", "") for c in t.questions.get(qf, [])}
            pw = self.cw * 46
        cur = shown if shown in items else items[0]
        bx = self.body.winfo_rootx() - self.ui.root.winfo_rootx() + x
        by = self.body.winfo_rooty() - self.ui.root.winfo_rooty() + y + h + 2
        self.ui.popup.show(self.ui.root, bx, by, pw, items, cur, self._popup_pick,
                           on_cancel=lambda: self.close_edit(commit=False, refocus=True),
                           labels=labels, hints=hints, openers=(holder, inner, lab))

    def _shown(self, t, col):
        return {"source": t.same_as}.get(col) or getattr(t, col, "")

    def _shown_label(self, t, col):
        if col == "gender":
            return self.marks.get(t.gender, "?")
        return self._shown(t, col)

    def _popup_pick(self, item, nxt):
        e = self.edit
        if not e:
            return
        t, col = e["term"], e["col"]
        if item == OTHER:
            i = self.index_of(t)
            self.close_edit(commit=False)
            self.start_edit(i, col, bypass=True)
            return
        self.close_edit(commit=False, refocus=True)
        self._store(t, col, item)
        if nxt:
            self._advance(t, col, nxt)

    def _store(self, t, col, value):
        changed = bool(self.apply and self.apply(t, FIELD_OF[col], value))
        if self.on_changed:
            self.on_changed()
        if changed and self.on_edited:
            self.on_edited(t)
        return changed

    def _entry_blur(self):
        e = self.edit
        if e and not e["closing"] and e.get("entry") and self.focus_get() is not e["entry"]:
            self.close_edit(commit=True)

    def _entry_done(self, how):
        e = self.edit
        if not e:
            return
        t, col = e["term"], e["col"]
        i = self.index_of(t)
        below = self.rows[i + 1] if i is not None and i + 1 < len(self.rows) else None
        self.close_edit(commit=True, refocus=True)
        if how == "down":
            if below is not None and self.index_of(below) is not None:
                self.select_index(self.index_of(below))
                self.start_edit(self.index_of(below), col if col in EDITABLE else "tr")
        else:
            self._advance(t, col, 1 if how == "next" else -1)

    def _advance(self, term, col, d):
        i = self.index_of(term)
        if i is None or col not in EDITABLE:
            return
        k = EDITABLE.index(col) + d
        if k >= len(EDITABLE):
            i, k = i + 1, 0
        elif k < 0:
            i, k = i - 1, len(EDITABLE) - 1
        if 0 <= i < len(self.rows):
            self.start_edit(i, EDITABLE[k])

    def close_edit(self, commit, refocus=False):
        e = self.edit
        if not e:
            return
        e["closing"] = True
        self.edit = None
        value = None
        if commit and e.get("entry"):
            value = e["entry"].get().strip()
        if self.ui.popup.open:
            self.ui.popup.close()
        e["holder"].destroy()
        self.draw()
        if refocus:
            self.body.focus_set()
        if value is not None and value != self._shown(e["term"], e["col"]):
            self._store(e["term"], e["col"], value)
        elif self.on_changed:
            self.on_changed()
