from __future__ import annotations
from dataclasses import dataclass
import traceback
from pathlib import Path


@dataclass(frozen=True)
class Location:
    path: str
    line: int

    def __str__(self) -> str:
        return f"{self.path}:{self.line}"


class EraError(Exception):
    def __init__(
        self,
        message: str,
        location: Location | None = None,
        code: str = "E_RUNTIME",
        *,
        diagnostic_message: str | None = None,
    ):
        super().__init__(message)
        self.message, self.location, self.code = message, location, code
        self.diagnostic_message = diagnostic_message
        self.era_stack: list[dict] = []

    def __str__(self) -> str:
        pos = f"{self.location}: " if self.location else ""
        from .diagnostic_format import reference_message

        return f"{pos}{self.code}: {(self.diagnostic_message if self.diagnostic_message is not None else reference_message(self.message,self.code))}"

    def as_dict(self) -> dict:
        from .diagnostic_format import reference_message

        result = {
            "code": self.code,
            "message": self.message,
            "diagnostic_message": (
                self.diagnostic_message
                if self.diagnostic_message is not None
                else reference_message(self.message, self.code)
            ),
            "internal_message": self.message,
            "file": self.location.path if self.location else None,
            "line": self.location.line if self.location else None,
            "stack": self.era_stack,
        }
        from .fatal_presentation import describe

        presentation = describe(self)
        if presentation is not None:
            result['diagnostic_message'] = presentation['message']
            result['diagnostic_presentation'] = presentation
        return result


class Unsupported(EraError):
    def __init__(self, message: str, location: Location | None = None):
        super().__init__(message, location, "E_UNSUPPORTED")


@dataclass(frozen=True)
class LoadDiagnostic:
    severity: int
    category: str
    location: Location
    source_text: str
    reference_message: str
    display_order: int
    phase: str = 'load-time'
    internal_message: str | None = None

    def as_dict(self):
        return {
            'kind': 'warning',
            'severity': self.severity,
            'category': self.category,
            'file': self.location.path,
            'line': self.location.line,
            'source_text': self.source_text,
            'diagnostic_phase': self.phase,
            'reference_message': self.reference_message,
            'display_order': self.display_order,
            'internal_message': self.internal_message,
        }


class InternalError(EraError):
    """Unexpected Python fault, with bounded developer diagnostics.

    Do not echo arbitrary exception text, source contents or local values into
    ERB reports. The original exception remains available through __cause__.
    """

    def __init__(self, cause: Exception, location: Location | None = None):
        self.python_exception_type = type(cause).__name__
        self.developer_frames = [
            {'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
            for f in traceback.extract_tb(cause.__traceback__)[-16:]
        ]
        super().__init__(
            'Unexpected Python '
            + self.python_exception_type
            + '; engine diagnostic required',
            location,
            'E_INTERNAL',
        )

    def as_dict(self):
        result = super().as_dict()
        result['internal_diagnostic'] = {
            'python_exception_type': self.python_exception_type,
            'frames': self.developer_frames,
            'source_and_locals_included': False,
        }
        return result


class FlowSignal(Exception):
    def __init__(self, state: str):
        self.state = state.upper()


class QuitSignal(Exception):
    pass


class TrainRequest(Exception):
    """A DOTRAIN transfer abandons script frames, but does not BEGIN TRAIN again."""

    def __init__(self, command: int):
        self.command = command
