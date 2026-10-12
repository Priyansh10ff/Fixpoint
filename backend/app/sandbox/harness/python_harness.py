"""Runs inside the sandbox: executes the user's file and, on an uncaught exception, prints the
normal traceback (without harness frames) plus one JSON line with the crashing frame's locals.

Kept dependency-free and compatible with Python 3.8+.
"""

import json
import reprlib
import runpy
import sys
import traceback

MARKER = "__FIXPOINT_CTX__"
MAX_LOCALS = 25

_repr = reprlib.Repr()
_repr.maxstring = 120
_repr.maxother = 120
_repr.maxlist = 12
_repr.maxdict = 12
_repr.maxset = 12
_repr.maxtuple = 12


def _safe_repr(value):
    try:
        return _repr.repr(value)
    except Exception:  # noqa: BLE001 - user objects can raise anything in __repr__
        return "<unrepresentable>"


def _interesting(name, value):
    if name.startswith("__") and name.endswith("__"):
        return False
    return not (callable(value) or type(value).__name__ == "module")


def main():
    target = sys.argv[1]
    sys.argv = sys.argv[1:]
    sys.path[0] = "/work"
    try:
        runpy.run_path(target, run_name="__main__")
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        tb = exc.__traceback__
        te = traceback.TracebackException(type(exc), exc, tb)
        te.stack = traceback.StackSummary.from_list([f for f in te.stack if f.filename == target])
        sys.stdout.flush()
        sys.stderr.write("".join(te.format()))

        frame, line = None, None
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == target:
                frame, line = tb.tb_frame, tb.tb_lineno
            tb = tb.tb_next
        if isinstance(exc, SyntaxError) and exc.filename == target:
            line = exc.lineno
        local_vars = {}
        function = None
        if frame is not None:
            function = frame.f_code.co_name
            for name, value in list(frame.f_locals.items()):
                if _interesting(name, value):
                    local_vars[name] = _safe_repr(value)
                if len(local_vars) >= MAX_LOCALS:
                    break
        ctx = {
            "error_type": type(exc).__name__,
            "message": str(exc)[:500],
            "line": line,
            "function": function,
            "locals": local_vars,
        }
        sys.stderr.write("\n" + MARKER + json.dumps(ctx) + "\n")
        sys.stderr.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()
