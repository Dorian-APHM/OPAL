"""
Shared SQL identifier validation for defense-in-depth against SQL injection.

All SQL identifiers (schema names, table names, column names) that are
interpolated into f-string queries MUST be validated through safe_identifier()
before use, even if they originate from static config or Pydantic-validated
fields.
"""
import re

# Strict pattern: must start with letter or underscore, then only
# alphanumeric and underscores. No dots, spaces, semicolons, etc.
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def safe_identifier(name: str) -> str:
    """Validate and return a safe SQL identifier (schema/table/column name).

    Raises ValueError if the identifier contains characters outside
    [A-Za-z0-9_] or does not start with a letter/underscore.

    This provides defense-in-depth: even values from DOMAIN_CONFIG (static)
    or Pydantic-validated omop_schema fields are checked before SQL
    interpolation.
    """
    if not isinstance(name, str) or not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError("Invalid SQL identifier")
    if len(name) > 63:
        raise ValueError("SQL identifier too long (max 63 characters)")
    return name
