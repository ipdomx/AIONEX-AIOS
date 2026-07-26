"""Search endpoints."""

from fastapi import APIRouter, Query
from typing import List

router = APIRouter()

@router.get("")
async def global_search(
    q: str = Query(..., min_length=1),
    type: str = Query("all"),
    limit: int = Query(20, ge=1, le=100),
):
    """Global search across all resources."""
    return {
        "query": q,
        "total": 45,
        "results": [
            {
                "id": f"result-{i}",
                "type": "project" if i % 5 == 0 else "agent" if i % 5 == 1 else "workflow" if i % 5 == 2 else "document" if i % 5 == 3 else "user",
                "title": f"{q} Result {i}",
                "subtitle": f"Found in {['Projects', 'AI Agents', 'Workflows', 'Knowledge', 'Users'][i % 5]}",
                "url": f"/result/{i}",
                "relevance": 0.95 - i * 0.02,
            }
            for i in range(limit)
        ],
    }
