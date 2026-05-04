from __future__ import annotations

from abc import ABC, abstractmethod

from models import AccessInfo, Paper


class DocumentAccessProvider(ABC):
    @abstractmethod
    def resolve(self, paper: Paper) -> AccessInfo:
        raise NotImplementedError
