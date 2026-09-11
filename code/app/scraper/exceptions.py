class HumanVerificationRequiredError(RuntimeError):
    """Raised when AVFan presents a human verification challenge."""


class EnrichmentStopRequested(RuntimeError):
    """Raised when a running enrichment operation is asked to stop."""
