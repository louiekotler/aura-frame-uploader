class AuraError(Exception):
    """Base for every error this tool raises deliberately."""


class ConfigError(AuraError):
    pass


class FrameNotAllowed(AuraError):
    """Raised when a write targets a frame outside the configured allowlist."""


class NotLoggedIn(AuraError):
    pass


class ApiError(AuraError):
    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


class UploadError(AuraError):
    pass


class ImageError(AuraError):
    pass
