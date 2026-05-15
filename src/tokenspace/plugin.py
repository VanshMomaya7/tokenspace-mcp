"""LanguagePlugin ABC. Python is the only implementation in Phase 1."""
from __future__ import annotations

from abc import ABC, abstractmethod

from tokenspace.types import EditResult

__all__ = ["LanguagePlugin"]


class LanguagePlugin(ABC):
    @abstractmethod
    def edit_function_body(
        self, file_path: str, function_name: str, new_body: str
    ) -> EditResult: ...

    @abstractmethod
    def edit_class_method(
        self, file_path: str, class_name: str, method_name: str, new_body: str
    ) -> EditResult: ...
