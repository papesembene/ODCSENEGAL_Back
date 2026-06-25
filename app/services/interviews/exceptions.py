"""Domain exceptions translated to HTTP responses by the route layer."""


class InterviewError(Exception):
    status_code = 400


class InterviewValidationError(InterviewError):
    status_code = 400


class InterviewNotFoundError(InterviewError):
    status_code = 404


class InterviewConflictError(InterviewError):
    status_code = 409


class InterviewForbiddenError(InterviewError):
    status_code = 403
