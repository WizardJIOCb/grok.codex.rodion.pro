"""
Go Rules Engine with support for Classic and Portal modes.
Pure Python, no external dependencies.
"""

from typing import List, Tuple, Set, Optional, Dict
from copy import deepcopy
import json

Board = List[List[int]]
Pos = Tuple[int, int]
Color = int  # 1 = Black, 2 = White, 0 = Empty

BLACK = 1
WHITE = 2
EMPTY = 0

PLAYER_NAMES = {BLACK: "Чёрные", WHITE: "Белые"}


class GoRules:
    def __init__(self, size: int = 19, mode: str = "classic"):
        if size not in (9, 13, 19):
            raise ValueError("Board size must be 9, 13 or 19")
        if mode not in ("classic", "portal"):
            raise ValueError("Mode must be 'classic' or 'portal'")

        self.size = size
        self.mode = mode
        self.portals: List[Pos] = self._compute_portals()

    def _compute_portals(self) -> List[Pos]:
        if self.mode != "portal":
            return []

        # Nice positions roughly near star points
        if self.size == 19:
            return [(3, 3), (3, 15), (15, 3), (15, 15)]
        elif self.size == 13:
            return [(2, 2), (2, 10), (10, 2), (10, 10)]
        else:  # 9x9
            return [(2, 2), (2, 6), (6, 2), (6, 6)]

    # ---------- Board helpers ----------

    def new_board(self) -> Board:
        return [[EMPTY for _ in range(self.size)] for _ in range(self.size)]

    def in_bounds(self, r: int, c: int) -> bool:
        return 0 <= r < self.size and 0 <= c < self.size

    def copy_board(self, board: Board) -> Board:
        return deepcopy(board)

    def get_neighbors(self, r: int, c: int) -> List[Pos]:
        deltas = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        return [(r + dr, c + dc) for dr, dc in deltas if self.in_bounds(r + dr, c + dc)]

    # ---------- Portal connectivity logic ----------

    def _get_portal_for_pos(self, r: int, c: int) -> Optional[int]:
        """Returns portal index if position is adjacent to a portal, else None."""
        if not self.portals:
            return None
        for idx, (pr, pc) in enumerate(self.portals):
            if abs(pr - r) + abs(pc - c) == 1:  # orthogonal only
                return idx
        return None

    def _build_portal_connections(self, board: Board) -> Dict[int, Set[Pos]]:
        """
        For each portal, collect all positions of stones adjacent to it.
        Returns {portal_index: set_of_adjacent_stone_positions}
        """
        if not self.portals:
            return {}

        connections: Dict[int, Set[Pos]] = {i: set() for i in range(len(self.portals))}
        for r in range(self.size):
            for c in range(self.size):
                if board[r][c] != EMPTY:
                    pidx = self._get_portal_for_pos(r, c)
                    if pidx is not None:
                        connections[pidx].add((r, c))
        return connections

    # ---------- Group / Liberty calculation (core) ----------

    def find_groups(self, board: Board) -> List[Dict]:
        """
        Returns list of groups:
        {
            "color": 1 or 2,
            "stones": set of (r,c),
            "liberties": set of (r,c),
            "portal_connected": bool (extra info for portal mode)
        }
        In portal mode, liberties and connectivity consider portal jumps.
        """
        visited = [[False] * self.size for _ in range(self.size)]
        groups = []
        portal_conns = self._build_portal_connections(board)

        # Map stone -> portal indices it belongs to
        stone_to_portals: Dict[Pos, Set[int]] = {}
        for pidx, stones in portal_conns.items():
            for pos in stones:
                stone_to_portals.setdefault(pos, set()).add(pidx)

        def flood(r: int, c: int, color: int):
            stack = [(r, c)]
            stones: Set[Pos] = set()
            liberties: Set[Pos] = set()
            connected_portals: Set[int] = set()

            while stack:
                cr, cc = stack.pop()
                if visited[cr][cc]:
                    continue
                visited[cr][cc] = True
                stones.add((cr, cc))

                if (cr, cc) in stone_to_portals:
                    connected_portals.update(stone_to_portals[(cr, cc)])

                for nr, nc in self.get_neighbors(cr, cc):
                    if board[nr][nc] == EMPTY:
                        liberties.add((nr, nc))
                    elif board[nr][nc] == color and not visited[nr][nc]:
                        stack.append((nr, nc))

            # === PORTAL MAGIC: merge liberties and stones across portals ===
            if self.mode == "portal" and connected_portals:
                for pidx in connected_portals:
                    for other_pos in portal_conns.get(pidx, set()):
                        if other_pos not in stones:
                            # Add the other stone as part of this group (virtual connection)
                            stones.add(other_pos)
                            # Add liberties of the other stone too
                            for nr, nc in self.get_neighbors(*other_pos):
                                if board[nr][nc] == EMPTY:
                                    liberties.add((nr, nc))

            return {
                "color": color,
                "stones": stones,
                "liberties": liberties,
                "portal_ids": list(connected_portals),
            }

        for r in range(self.size):
            for c in range(self.size):
                if board[r][c] != EMPTY and not visited[r][c]:
                    groups.append(flood(r, c, board[r][c]))

        return groups

    def get_group_at(self, board: Board, r: int, c: int) -> Optional[Dict]:
        if not self.in_bounds(r, c) or board[r][c] == EMPTY:
            return None
        for g in self.find_groups(board):
            if (r, c) in g["stones"]:
                return g
        return None

    # ---------- Move validation & application ----------

    def is_suicide(self, board: Board, r: int, c: int, color: int) -> bool:
        """Would this move leave the placed stone/group with zero liberties (ignoring ko for now)."""
        test = self.copy_board(board)
        test[r][c] = color

        # First remove any opponent groups that might be captured
        opp = WHITE if color == BLACK else BLACK
        groups = self.find_groups(test)
        captured = []
        for g in groups:
            if g["color"] == opp and len(g["liberties"]) == 0:
                for sr, sc in g["stones"]:
                    test[sr][sc] = EMPTY
                    captured.append((sr, sc))

        # Recompute for own group
        own_group = self.get_group_at(test, r, c)
        return own_group is not None and len(own_group["liberties"]) == 0 and not captured

    def is_ko_move(self, board: Board, r: int, c: int, color: int, last_ko: Optional[Pos]) -> bool:
        """Simple ko: forbid immediate recapture of the single stone that was just captured."""
        if last_ko is None:
            return False
        return (r, c) == last_ko

    def is_legal_move(
        self,
        board: Board,
        r: int,
        c: int,
        color: int,
        last_ko: Optional[Pos] = None,
    ) -> Tuple[bool, str]:
        if not self.in_bounds(r, c):
            return False, "Ход за пределами доски"
        if board[r][c] != EMPTY:
            return False, "Пункт уже занят"
        if (r, c) in self.portals:
            return False, "Нельзя ставить на портал"

        if self.is_ko_move(board, r, c, color, last_ko):
            return False, "Нельзя сразу брать ко (правило Ко)"

        # Suicide check (after considering captures)
        if self.is_suicide(board, r, c, color):
            return False, "Самоубийственный ход"

        return True, ""

    def apply_move(
        self,
        board: Board,
        r: int,
        c: int,
        color: int,
        last_ko: Optional[Pos] = None,
    ) -> Tuple[Board, List[Pos], Optional[Pos]]:
        """
        Apply a move. Returns (new_board, captured_positions, new_ko_position)
        Raises ValueError if illegal.
        """
        legal, reason = self.is_legal_move(board, r, c, color, last_ko)
        if not legal:
            raise ValueError(reason)

        new_board = self.copy_board(board)
        new_board[r][c] = color

        # Capture opponent stones that now have 0 liberties
        opp = WHITE if color == BLACK else BLACK
        groups = self.find_groups(new_board)
        captured: List[Pos] = []

        for g in groups:
            if g["color"] == opp and len(g["liberties"]) == 0:
                for sr, sc in g["stones"]:
                    if new_board[sr][sc] == opp:  # safety
                        new_board[sr][sc] = EMPTY
                        captured.append((sr, sc))

        # Determine new ko position (only single stone capture creates ko)
        new_ko: Optional[Pos] = None
        if len(captured) == 1:
            # Check if the move we just made has exactly one liberty now
            own_group = self.get_group_at(new_board, r, c)
            if own_group and len(own_group["liberties"]) == 1:
                new_ko = next(iter(own_group["liberties"]))

        return new_board, captured, new_ko

    # ---------- Scoring (Chinese area rules) ----------

    def calculate_score(self, board: Board, komi: float = 7.5) -> Dict:
        """
        Chinese-style area scoring.
        Score = number of stones on board + number of surrounded empty points.
        """
        groups = self.find_groups(board)

        black_stones = 0
        white_stones = 0
        for g in groups:
            if g["color"] == BLACK:
                black_stones += len(g["stones"])
            else:
                white_stones += len(g["stones"])

        # Territory: empty points completely surrounded by one color
        visited = [[False] * self.size for _ in range(self.size)]
        black_territory = 0
        white_territory = 0

        def flood_territory(r: int, c: int) -> Tuple[int, int, bool]:
            """Returns (black_border, white_border, is_territory)"""
            stack = [(r, c)]
            local_visited: Set[Pos] = set()
            borders_black = False
            borders_white = False

            while stack:
                cr, cc = stack.pop()
                if (cr, cc) in local_visited:
                    continue
                local_visited.add((cr, cc))
                visited[cr][cc] = True

                for nr, nc in self.get_neighbors(cr, cc):
                    val = board[nr][nc]
                    if val == EMPTY and not visited[nr][nc] and (nr, nc) not in local_visited:
                        stack.append((nr, nc))
                    elif val == BLACK:
                        borders_black = True
                    elif val == WHITE:
                        borders_white = True

            is_territory = borders_black != borders_white  # only one color borders it
            return (1 if borders_black and not borders_white else 0,
                    1 if borders_white and not borders_black else 0,
                    is_territory)

        for r in range(self.size):
            for c in range(self.size):
                if board[r][c] == EMPTY and not visited[r][c]:
                    b, w, is_t = flood_territory(r, c)
                    if is_t:
                        black_territory += b
                        white_territory += w

        black_score = black_stones + black_territory
        white_score = white_stones + white_territory + komi

        winner = None
        if black_score > white_score:
            winner = BLACK
        elif white_score > black_score:
            winner = WHITE

        return {
            "black": round(black_score, 1),
            "white": round(white_score, 1),
            "black_stones": black_stones,
            "white_stones": white_stones,
            "black_territory": black_territory,
            "white_territory": white_territory,
            "komi": komi,
            "winner": winner,
            "mode": self.mode,
        }

    def pass_move(self, board: Board) -> Board:
        """Pass does not change the board."""
        return self.copy_board(board)

    # ---------- Utility ----------

    def board_to_dict(self, board: Board) -> List[List[int]]:
        return [row[:] for row in board]

    def portals_to_list(self) -> List[List[int]]:
        return [[p[0], p[1]] for p in self.portals]


# Quick self-test when run directly
if __name__ == "__main__":
    print("Testing Go Engine...")
    rules = GoRules(size=9, mode="portal")
    b = rules.new_board()

    # Place a few stones
    b[4][4] = BLACK
    b[4][5] = WHITE

    print("Portals:", rules.portals)
    groups = rules.find_groups(b)
    print(f"Groups found: {len(groups)}")
    for g in groups:
        print(f"  Color {g['color']}: {len(g['stones'])} stones, {len(g['liberties'])} libs, portals={g['portal_ids']}")

    print("Engine loaded successfully.")