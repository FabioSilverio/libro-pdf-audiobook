"""Custom exception classes for the application."""


class AppException(Exception):
    """Base exception class for application errors."""

    def __init__(self, message: str, code: str, status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(self.message)


class PDFProcessingError(AppException):
    """Raised when PDF processing fails."""

    def __init__(self, message: str = "Failed to process PDF"):
        super().__init__(message=message, code="PDF_PROCESSING_ERROR", status_code=422)


class EncryptedPDFError(AppException):
    """Raised when PDF is encrypted/password protected."""

    def __init__(self, message: str = "PDF is password protected"):
        super().__init__(message=message, code="ENCRYPTED_PDF", status_code=422)


class EmptyPDFError(AppException):
    """Raised when PDF contains no readable text."""

    def __init__(self, message: str = "PDF contains no readable text"):
        super().__init__(message=message, code="EMPTY_PDF", status_code=422)


class SummarizationError(AppException):
    """Raised when AI summarization fails."""

    def __init__(self, message: str = "Failed to generate summary"):
        super().__init__(message=message, code="SUMMARIZATION_ERROR", status_code=500)


class TTSGenerationError(AppException):
    """Raised when text-to-speech generation fails."""

    def __init__(self, message: str = "Failed to generate audio"):
        super().__init__(message=message, code="TTS_GENERATION_ERROR", status_code=500)


class TaskNotFoundError(AppException):
    """Raised when a task ID is not found."""

    def __init__(self, task_id: str):
        super().__init__(
            message=f"Task {task_id} not found",
            code="TASK_NOT_FOUND",
            status_code=404
        )


class FileValidationError(AppException):
    """Raised when file validation fails."""

    def __init__(self, message: str = "Invalid file"):
        super().__init__(message=message, code="FILE_VALIDATION_ERROR", status_code=422)
