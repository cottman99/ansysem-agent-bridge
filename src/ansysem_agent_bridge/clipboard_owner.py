"""Keep an X11 clipboard selection available until another application replaces it."""

from __future__ import annotations

import sys


def main() -> None:
    import tkinter

    text = sys.stdin.read(32769)
    if not text or len(text.encode("utf-8")) > 32768:
        raise ValueError("Clipboard context is empty or exceeds its size limit")
    root = tkinter.Tk()
    root.withdraw()
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()
    owner = str(root.tk.call("selection", "own", "-selection", "CLIPBOARD"))

    def check_owner() -> None:
        if str(root.tk.call("selection", "own", "-selection", "CLIPBOARD")) != owner:
            root.destroy()
        else:
            root.after(1000, check_owner)

    root.after(1000, check_owner)
    print("ready", flush=True)
    root.mainloop()


if __name__ == "__main__":
    main()
