"""Flag values in three layers: preset (read live) <- user (persisted) <- owned (computed per build).

The user layer maps flag id -> value, or None (a tombstone: the user switched a preset flag off)."""
from . import flagrules


class FlagState:
    def __init__(self, presets, preset="", user=None):
        self.presets = presets
        self.preset = preset
        self.user = {}
        for fid, val in (user or {}).items():
            if not flagrules.is_owned(fid):
                self.user[fid] = val

    # ------------------------------------------------------------------ layers
    def preset_flags(self):
        return self.presets.get(self.preset, {})

    def set_preset(self, name):
        self.preset = name

    def effective(self, owned=None):
        """preset <- user <- owned, without tombstones."""
        out = dict(self.preset_flags())
        for fid, val in self.user.items():
            if val is None:
                out.pop(fid, None)
            else:
                out[fid] = val
        for fid, val in (owned or {}).items():
            out[fid] = val
        return out

    def get(self, fid, default=None):
        return self.effective().get(fid, default)

    def origin(self, fid):
        """'user' (set or changed by the user), 'preset', 'hidden' (preset flag switched off) or None."""
        if fid in self.user:
            return "hidden" if self.user[fid] is None else "user"
        return "preset" if fid in self.preset_flags() else None

    # ------------------------------------------------------------------ edits
    def set(self, fid, value):
        """Returns False (and changes nothing) for an owned flag."""
        if flagrules.is_owned(fid):
            return False
        if fid in self.preset_flags() and self.preset_flags()[fid] == value:
            self.user.pop(fid, None)  # same as the preset: no user layer entry
        else:
            self.user[fid] = value
        return True

    def remove(self, fid):
        """Stop using the flag: a preset flag gets a tombstone, a user flag is deleted."""
        if fid in self.preset_flags():
            self.user[fid] = None
        else:
            self.user.pop(fid, None)

    def revert(self, fid):
        """Back to the preset value (or to nothing for a pure user flag)."""
        self.user.pop(fid, None)

    def differs(self):
        """True when a preset flag is switched off or changed by the user."""
        return any(fid in self.user for fid in self.preset_flags())

    def reset_preset(self):
        """Bring every preset flag back to its preset value; flags the user added on top stay. True when changed."""
        gone = [fid for fid in self.preset_flags() if fid in self.user]
        for fid in gone:
            del self.user[fid]
        return bool(gone)

    # ------------------------------------------------------------------ persistence
    def to_json(self):
        return {fid: val for fid, val in self.user.items() if not flagrules.is_transient(fid)}

    @classmethod
    def from_json(cls, presets, preset, data):
        return cls(presets, preset, data if isinstance(data, dict) else {})

    def unknown(self, inventory):
        """User flags the engine does not have (an engine update removed or renamed them)."""
        known = {f["id"] for f in (inventory or {}).get("flags", [])}
        return [fid for fid in self.user if known and fid not in known]
