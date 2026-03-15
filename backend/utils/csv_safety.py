"""CSV formula injection protection."""


def csv_safe(val):
    """Prevent CSV formula injection by prefixing dangerous characters."""
    s = str(val) if val is not None else ""
    if s and s[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + s
    return s
