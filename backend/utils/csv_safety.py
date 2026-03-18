"""CSV formula injection protection."""


_DANGEROUS_CHARS = {'=', '+', '-', '@', '\t', '\r'}


def csv_safe(val):
    """Prevent CSV formula injection by prefixing dangerous characters.

    Strips leading whitespace first so that payloads like ``" =1+1"`` are
    caught even when the dangerous character is not at position 0.
    """
    s = str(val).strip() if val is not None else ""
    if s and s[0] in _DANGEROUS_CHARS:
        return "'" + s
    return s
