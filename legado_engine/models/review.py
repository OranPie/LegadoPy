from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ReviewEntry:
    avatar: str = ""
    content: str = ""
    postTime: str = ""
    quoteUrl: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "avatar": self.avatar,
            "content": self.content,
            "postTime": self.postTime,
            "quoteUrl": self.quoteUrl,
        }


__all__ = ["ReviewEntry"]
