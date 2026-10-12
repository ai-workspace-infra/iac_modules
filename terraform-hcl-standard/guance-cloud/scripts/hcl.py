#!/usr/bin/env python3
"""Serialize plain Python data as explicit, ``terraform fmt``-stable HCL literals.

Loops live here (Python), never in the generated HCL.
"""
import json
import re

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


class Raw:
    """A verbatim HCL reference such as ``guance_notify_object.ops.uuid``."""

    def __init__(self, expression):
        self.expression = expression


def string(value):
    # Escape template sequences so values stay literal in HCL.
    return json.dumps(value, ensure_ascii=False).replace("${", "$${").replace("%{", "%%{")


def _key(name):
    return name if _IDENT.match(name) else string(name)


def _is_scalar(item):
    return item is None or isinstance(item, (str, int, float, bool, Raw))


def to_hcl(value, indent=0):
    """Render ``value`` as an HCL expression at nesting depth ``indent``."""
    pad = "  " * (indent + 1)
    end = "  " * indent
    if isinstance(value, Raw):
        return value.expression
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return string(value)
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        if all(_is_scalar(item) for item in value):
            return "[" + ", ".join(to_hcl(item) for item in value) + "]"
        return "[\n" + "".join(f"{pad}{to_hcl(item, indent + 1)},\n" for item in value) + end + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "{\n" + hcl_body(value, indent + 1) + "\n" + end + "}"
    raise TypeError(f"unsupported value for HCL: {type(value).__name__}")


def hcl_body(attrs, indent=1):
    """Render attributes as ``key = value`` lines, aligned like ``terraform fmt``.

    ``fmt`` aligns ``=`` across consecutive single-line attributes; attributes whose
    value spans lines are neither aligned nor part of a group.
    """
    pad = "  " * indent
    rendered = [(_key(key), to_hcl(attrs[key], indent)) for key in sorted(attrs)]
    lines = []
    group = []

    def flush():
        if group:
            width = max(len(name) for name, _ in group)
            lines.extend(f"{pad}{name.ljust(width)} = {text}" for name, text in group)
            group.clear()

    for name, text in rendered:
        if "\n" in text:
            flush()
            lines.append(f"{pad}{name} = {text}")
        else:
            group.append((name, text))
    flush()
    return "\n".join(lines)
