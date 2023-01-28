class ApiError(Exception):
    """Class for any api errors."""

    def __init__(self, *args, **kwargs):
        """Initialize an ApiError."""
        Exception.__init__(self, *args, **kwargs)
