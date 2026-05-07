from abc import ABC, abstractmethod
from typing import List

from models import Listing, SearchParams


class BaseScraper(ABC):
    name: str = "base"

    @abstractmethod
    def search(self, params: SearchParams) -> List[Listing]:
        """Run a property search and return a list of Listing objects."""
        ...

    def _safe_int(self, val) -> int | None:
        try:
            return int(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    def _safe_float(self, val) -> float | None:
        try:
            return float(val) if val is not None else None
        except (ValueError, TypeError):
            return None
