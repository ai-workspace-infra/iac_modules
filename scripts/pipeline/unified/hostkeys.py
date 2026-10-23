"""Parse a complete public SSH fingerprint from a narrow cloud serial console."""
import base64
import re

from .contracts import require


def console_fingerprint(text):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    # Console snapshots may repeat frames. Accept only a complete framed value,
    # never a fingerprint prefix or an unframed authorized-user key.
    fingerprints = set()
    parts = None
    for line in text.replace("\r", "\n").splitlines():
        if "IAC_ED25519_FP_BEGIN" in line:
            parts = []
        elif "IAC_ED25519_FP_END" in line:
            if parts is not None:
                value = "".join(parts)
                if re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", value):
                    fingerprints.add(value)
            parts = None
        elif parts is not None:
            token = line.strip().split()[-1:]
            if token and re.fullmatch(r"(?:SHA256:)?[A-Za-z0-9+/]{1,24}", token[0]):
                parts.append(token[0])
    require(len(fingerprints) == 1, "one complete trusted cloud fingerprint is required")
    value = next(iter(fingerprints))
    require(len(base64.b64decode(value[7:] + "=", validate=True)) == 32, "invalid cloud fingerprint")
    return value
