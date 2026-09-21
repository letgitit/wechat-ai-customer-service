from .models import ChatSnapshot, MessageObservation


class GapError(ValueError):
    pass


class Delta:
    def __init__(self):
        self.previous: ChatSnapshot | None = None
        self.seen: set[str] = set()

    def reset(self):
        self.previous = None
        self.seen.clear()

    def check(self, current: ChatSnapshot) -> tuple[MessageObservation, ...]:
        ids = [m.ui_id for m in current.messages]
        if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
            raise GapError("AMBIGUOUS_UI_ID")
        prev = self.previous
        if prev is None:
            return ()
        if (prev.binding_id, prev.binding_epoch) != (current.binding_id, current.binding_epoch):
            raise GapError("REBIND_REQUIRED")
        before = [m.identity() for m in prev.messages]
        after = [m.identity() for m in current.messages]
        if not before:
            new = current.messages
        else:
            # 只有旧窗口后缀 == 新窗口前缀才构成连续锚点。
            overlap = next(
                (n for n in range(min(len(before), len(after)), 0, -1) if before[-n:] == after[:n]),
                0,
            )
            if not overlap:
                raise GapError("GAP_DETECTED")
            new = current.messages[overlap:]
        if any(m.ui_id in self.seen for m in new):
            raise GapError("UI_ID_REUSED")
        return new

    def update(self, current: ChatSnapshot) -> tuple[MessageObservation, ...]:
        new = self.check(current)
        self.previous = current
        self.seen.update(m.ui_id for m in current.messages)
        return new
