"""
Grok Go Online — FastAPI backend
Classic Go + original Portal Go mode
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os

from app.models import CreateSessionRequest, JoinSessionRequest, MoveRequest
from app.game_manager import manager, BLACK, WHITE

app = FastAPI(
    title="Grok Go Online",
    description="Онлайн Го с классическим режимом и оригинальным режимом Portal Go",
    version="1.0.0",
)

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static frontend
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main game UI."""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse(
        content="<h1>Grok Go</h1><p>Frontend not found. Please create static/index.html</p>",
        status_code=200,
    )


# ---------- REST API ----------

@app.post("/api/sessions")
async def create_session(req: CreateSessionRequest):
    """Create a new game session."""
    session = manager.create_session(
        player_name=req.player_name,
        mode=req.mode,
        board_size=req.board_size,
        komi=req.komi,
    )
    return {
        "code": session.code,
        "mode": session.mode,
        "board_size": session.size,
        "your_color": BLACK,
        "info": session.to_info().model_dump(),
    }


@app.post("/api/sessions/join")
async def join_session(req: JoinSessionRequest):
    """Join an existing session as White."""
    session = manager.get_session(req.session_code)
    if not session:
        raise HTTPException(404, "Сессия не найдена")

    if session.is_full():
        raise HTTPException(400, "Сессия уже заполнена")

    # Prevent same name
    if session.players[BLACK] and session.players[BLACK].name.lower() == req.player_name.lower():
        raise HTTPException(400, "Имя уже занято в этой сессии")

    try:
        color = session.add_player(req.player_name)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "code": session.code,
        "mode": session.mode,
        "board_size": session.size,
        "your_color": color,
        "info": session.to_info().model_dump(),
    }


@app.get("/api/sessions")
async def list_sessions():
    """List open (not full, not finished) sessions."""
    return {"sessions": [s.model_dump() for s in manager.list_open_sessions()]}


@app.get("/api/sessions/{code}")
async def get_session_info(code: str):
    session = manager.get_session(code)
    if not session:
        raise HTTPException(404, "Сессия не найдена")
    return session.to_info().model_dump()


# ---------- WebSocket for real-time play ----------

@app.websocket("/ws/{code}")
async def websocket_endpoint(websocket: WebSocket, code: str, color: int):
    """
    WebSocket connection for a specific player in a session.
    Query param: ?color=1 (Black) or color=2 (White)
    """
    await websocket.accept()

    color = int(color)
    if color not in (BLACK, WHITE):
        await websocket.send_json({"type": "error", "error": "Неверный цвет игрока"})
        await websocket.close()
        return

    session = await manager.connect_player(code, color, websocket)
    if not session:
        await websocket.send_json({"type": "error", "error": "Сессия не найдена"})
        await websocket.close()
        return

    try:
        while True:
            data = await websocket.receive_json()

            msg_type = data.get("type")

            if msg_type == "move":
                row = data.get("row")
                col = data.get("col")
                success, error, _ = await manager.make_move(code, color, row, col)
                if not success:
                    await websocket.send_json({"type": "error", "error": error})

            elif msg_type == "pass":
                success, error, _ = await manager.pass_turn(code, color)
                if not success:
                    await websocket.send_json({"type": "error", "error": error})

            elif msg_type == "resign":
                await manager.resign(code, color)

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect_player(code, color)
    except Exception as e:
        manager.disconnect_player(code, color)
        print(f"WS error: {e}")


# ---------- Health & Info ----------

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "active_sessions": len(manager.sessions),
        "modes": ["classic", "portal"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)