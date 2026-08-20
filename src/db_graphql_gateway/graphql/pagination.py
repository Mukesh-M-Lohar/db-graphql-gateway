import base64
import json
from typing import Generic, TypeVar, Optional
import strawberry

T = TypeVar("T")


@strawberry.type
class PageInfo:
    has_next_page: bool
    has_previous_page: bool
    start_cursor: Optional[str] = None
    end_cursor: Optional[str] = None


@strawberry.type
class Edge(Generic[T]):
    node: T
    cursor: str


@strawberry.type
class Connection(Generic[T]):
    edges: list[Edge[T]]
    page_info: PageInfo
    total_count: Optional[int] = None


def encode_cursor(offset: int) -> str:
    payload = json.dumps({"offset": offset})
    return base64.b64encode(payload.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor: str) -> int:
    try:
        decoded = base64.b64decode(cursor.encode("utf-8")).decode("utf-8")
        data = json.loads(decoded)
        return int(data.get("offset", 0))
    except Exception:
        raise ValueError(f"Invalid cursor format: {cursor}")
