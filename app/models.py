"""
Pydantic models for the Go Online API.
"""

from typing import Optional, List, Dict, Literal
from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    player_name: str = Field(..., min_length=1, max_length=32)
    mode: Literal["classic", "portal"] = "classic"
    board_size: Literal[9, 13, 19] = 19
    komi: float = 7.5


class JoinSessionRequest(BaseModel):
    player_name: str = Field(..., min_length=1, max_length=32)
    session_code: str = Field(..., min_length=3, max_length=8)


class MoveRequest(BaseModel):
    row: int
    col: int


class SessionInfo(BaseModel):
    code: str
    mode: str
    board_size: int
    komi: float
    players: Dict[str, Optional[str]]  # "1": name or null, "2": ...
    current_player: int
    moves_count: int
    game_over: bool
    winner: Optional[int] = None


class GameState(BaseModel):
    code: str
    mode: str
    board_size: int
    komi: float
    board: List[List[int]]
    portals: List[List[int]]
    current_player: int
    players: Dict[str, Optional[str]]
    captured: Dict[str, int]  # {"1": x, "2": y}
    last_move: Optional[List[int]] = None  # [r, c] or null
    game_over: bool
    winner: Optional[int] = None
    score: Optional[Dict] = None
    your_color: Optional[int] = None  # Filled per client in WS messages


class WSMessage(BaseModel):
    type: str
    data: Dict = Field(default_factory=dict)
    error: Optional[str] = None