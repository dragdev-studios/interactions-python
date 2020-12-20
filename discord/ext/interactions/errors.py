
class InteractionsError(Exception):
    """Base error for interactions errors."""

class ExpiredToken(InteractionsError):
    """Raised when an attempt is made to modify a previous followup that was made 15 or more minutes ago."""
