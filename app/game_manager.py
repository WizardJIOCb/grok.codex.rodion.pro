"""
Game session manager + WebSocket connection handling.
In-memory only (perfect for this environment).
"""

import asyncio
import random
import string
from typing import Dict, Optional, Set, List, Tuple
from datetime import datetime

from fastapi import WebSocket
from app.go_engine import GoRules, BLACK, WHITE, EMPTY
from app.models import GameState, SessionInfo


class Player:
    def __init__(self, name: str, color: int):
        self.name = name
        self.color = color
        self.connected = False
        self.ws: Optional[WebSocket] = None


class GameSession:
    def __init__(self, code: str, mode: str, size: int, komi: float, creator_name: str):
        self.code = code
        self.mode = mode
        self.size = size
        self.komi = komi
        self.rules = GoRules(size=size, mode=mode)

        self.board = self.rules.new_board()
        self.current_player = BLACK
        self.last_ko: Optional[Tuple[int, int]] = None
        self.last_move: Optional[Tuple[int, int]] = None
        self.pass_count = 0
        self.captured = {BLACK: 0, WHITE: 0}
        self.move_history: List[Tuple[int, int, int]] = []  # (r, c, color) for potential future use

        self.players: Dict[int, Optional[Player]] = {
            BLACK: Player(creator_name, BLACK),
            WHITE: None,
        }
        self.game_over = False
        self.winner: Optional[int] = None
        self.score: Optional[Dict] = None
        self.created_at = datetime.utcnow()

        # WebSocket connections for broadcasting
        self.connections: Dict[int, WebSocket] = {}  # color -> ws

    def is_full(self) -> bool:
        return self.players[WHITE] is not None

    def get_player_color(self, name: str) -> Optional[int]:
        for color, p in self.players.items():
            if p and p.name.lower() == name.lower():
                return color
        return None

    def add_player(self, name: str) -> int:
        if self.players[WHITE] is None:
            self.players[WHITE] = Player(name, WHITE)
            return WHITE
        raise ValueError("Session is full")

    def to_info(self) -> SessionInfo:
        return SessionInfo(
            code=self.code,
            mode=self.mode,
            board_size=self.size,
            komi=self.komi,
            players={
                "1": self.players[1].name if self.players[1] else None,
                "2": self.players[2].name if self.players[2] else None,
            },
            current_player=self.current_player,
            moves_count=len(self.move_history),
            game_over=self.game_over,
            winner=self.winner,
        )

    def to_state(self, for_color: Optional[int] = None) -> GameState:
        state = GameState(
            code=self.code,
            mode=self.mode,
            board_size=self.size,
            komi=self.komi,
            board=self.rules.board_to_dict(self.board),
            portals=self.rules.portals_to_list(),
            current_player=self.current_player,
            players={
                "1": self.players[1].name if self.players[1] else None,
                "2": self.players[2].name if self.players[2] else None,
            },
            captured={str(k): v for k, v in self.captured.items()},
            last_move=list(self.last_move) if self.last_move else None,
            game_over=self.game_over,
            winner=self.winner,
            score=self.score,
        )
        if for_color:
            state.your_color = for_color
        return state

    async def broadcast(self, message: dict):
        """Send message to all connected players."""
        dead = []
        for color, ws in list(self.connections.items()):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(color)
        for color in dead:
            self.connections.pop(color, None)

    async def broadcast_state(self, event_type: str = "state"):
        state_msg = {
            "type": event_type,
            "data": self.to_state().model_dump(),
        }
        await self.broadcast(state_msg)


class GameManager:
    def __init__(self):
        self.sessions: Dict[str, GameSession] = {}
        self.code_length = 5

    def _generate_code(self) -> str:
        """Generate a short, human-friendly session code."""
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=self.code_length))
            if code not in self.sessions:
                return code

    def create_session(
        self,
        player_name: str,
        mode: str = "classic",
        board_size: int = 19,
        komi: float = 7.5,
    ) -> GameSession:
        code = self._generate_code()
        session = GameSession(code, mode, board_size, komi, player_name)
        self.sessions[code] = session
        return session

    def get_session(self, code: str) -> Optional[GameSession]:
        return self.sessions.get(code.upper())

    def list_open_sessions(self) -> List[SessionInfo]:
        result = []
        for sess in self.sessions.values():
            if not sess.game_over and not sess.is_full():
                result.append(sess.to_info())
        return result

    async def make_move(
        self, code: str, color: int, row: int, col: int
    ) -> Tuple[bool, str, Optional[GameSession]]:
        sess = self.get_session(code)
        if not sess:
            return False, "Сессия не найдена", None

        if sess.game_over:
            return False, "Игра уже закончена", None

        if sess.current_player != color:
            return False, "Сейчас не ваш ход", None

        if not sess.players[color]:
            return False, "Вы не участвуете в этой партии", None

        try:
            new_board, captured, new_ko = sess.rules.apply_move(
                sess.board, row, col, color, sess.last_ko
            )
        except ValueError as e:
            return False, str(e), None

        # Apply successful move
        sess.board = new_board
        sess.last_ko = new_ko
        sess.last_move = (row, col)
        sess.current_player = WHITE if color == BLACK else BLACK
        sess.pass_count = 0

        # Update captured count
        if captured:
            opp = WHITE if color == BLACK else BLACK
            sess.captured[color] += len(captured)

        sess.move_history.append((row, col, color))

        # Broadcast updated state
        await sess.broadcast_state("move")

        return True, "", sess

    async def pass_turn(self, code: str, color: int) -> Tuple[bool, str, Optional[GameSession]]:
        sess = self.get_session(code)
        if not sess or sess.game_over:
            return False, "Невозможно сделать пасс", None
        if sess.current_player != color:
            return False, "Сейчас не ваш ход", None

        sess.current_player = WHITE if color == BLACK else BLACK
        sess.pass_count += 1
        sess.last_move = None
        sess.last_ko = None

        if sess.pass_count >= 2:
            await self._end_game(sess)
        else:
            await sess.broadcast_state("pass")

        return True, "", sess

    async def resign(self, code: str, color: int) -> Tuple[bool, str, Optional[GameSession]]:
        sess = self.get_session(code)
        if not sess or sess.game_over:
            return False, "Невозможно сдаться", None

        winner = WHITE if color == BLACK else BLACK
        sess.game_over = True
        sess.winner = winner
        sess.score = {
            "winner": winner,
            "by_resign": True,
        }

        await sess.broadcast_state("game_over")
        return True, "", sess

    async def _end_game(self, sess: GameSession):
        sess.game_over = True
        score = sess.rules.calculate_score(sess.board, sess.komi)
        sess.score = score
        sess.winner = score.get("winner")
        await sess.broadcast_state("game_over")

    async def connect_player(
        self, code: str, color: int, websocket: WebSocket
    ) -> Optional[GameSession]:
        sess = self.get_session(code)
        if not sess:
            return None

        sess.connections[color] = websocket
        if sess.players[color]:
            sess.players[color].connected = True

        # Send current state immediately
        await websocket.send_json({
            "type": "welcome",
            "data": sess.to_state(for_color=color).model_dump(),
        })

        # Notify others
        await sess.broadcast({
            "type": "player_connected",
            "data": {"color": color, "name": sess.players[color].name if sess.players[color] else "?"},
        })

        return sess

    def disconnect_player(self, code: str, color: int):
        sess = self.get_session(code)
        if not sess:
            return
        sess.connections.pop(color, None)
        if sess.players[color]:
            sess.players[color].connected = False


# Global singleton manager
manager = GameManager()