"""Parse a complete public SSH fingerprint from a narrow cloud serial console."""
import base64
import hashlib
import re

from .contracts import require


def console_fingerprint(text):
    # A Weblish redraw uses vertical cursor positioning rather than newlines.
    text = re.sub(r"\x1b\[[0-9;]*[HfABEF]", "\n", text)
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
    # Canonical cloud-init keys-to-console writes complete public host keys in
    # this explicit frame. Authorized-user keys and unframed prefixes are ignored.
    for block in re.findall(r"-----BEGIN SSH HOST KEY KEYS-----(.*?)-----END SSH HOST KEY KEYS-----", text, re.S):
        for match in re.finditer(r"ssh-ed25519[ \t]+((?:[A-Za-z0-9+/=][ \t\r\n]*){67}[A-Za-z0-9+/=])(?=\s|$)", block):
            encoded = re.sub(r"\s", "", match[1])
            try:
                key = base64.b64decode(encoded, validate=True)
            except ValueError:
                continue
            # Complete SSH wire format: 11-byte algorithm name and 32-byte key.
            if len(key) != 51 or key[:19] != b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20":
                continue
            fingerprints.add("SHA256:" + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("="))
    require(len(fingerprints) == 1, "one complete trusted cloud fingerprint is required")
    value = next(iter(fingerprints))
    require(len(base64.b64decode(value[7:] + "=", validate=True)) == 32, "invalid cloud fingerprint")
    return value
