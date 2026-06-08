import json
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from db.database import init_db
from core.orchestrator import Orchestrator
from memory.long_term import get_active_interests
from memory.tree_api import (
    get_memory_tree_node,
    list_memory_tree_roots,
    search_memory_tree,
)

orchestrator = Orchestrator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Knowledge Agent", version="0.1.0", lifespan=lifespan)


#CORS —— 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "knowledge-agent"}


@app.post("/chat")
async def chat(request: Request):
    """普通对话：用户消息 → 自动路由到合适的 Agent"""
    body = await request.json()
    message = body.get("message", "")

    try:
        result = await orchestrator.route_and_execute(message)
    except Exception as e:
        return {
            "agent": "system",
            "response": f"系统暂时不可用，请稍后重试。({str(e)[:100]})",
            "tool_calls": [],
            "session_id": "",
        }

    return {
        "agent": result["agent"],
        "response": result["response"],
        "tool_calls": result.get("tool_calls", []),
        "session_id": result["session_id"],
    }


@app.post("/negotiate")
async def negotiate(request: Request):
    """多 Agent 协商：广播任务，Agent 通过 MessageBus 自主通信"""
    body = await request.json()
    task = body.get("task", "")

    result = await orchestrator.negotiate(task)

    return {
        "task": result["task"],
        "final_answer": result["final_answer"],
        "message_history": result["message_history"],
    }


@app.get("/memory/interests")
async def memory_interests():
    """查询用户长期兴趣"""
    interests = await get_active_interests()
    return {"interests": interests}


@app.get("/memory/tree")
async def memory_tree(tree_type: str | None = None, level: int = 2, limit: int = 100):
    """查询 Memory Tree 高层节点，默认返回 L2 roots"""
    return await list_memory_tree_roots(
        tree_type=tree_type,
        level=level,
        limit=limit,
    )


@app.get("/memory/tree/search")
async def memory_tree_search(
    q: str,
    tree_type: str | None = None,
    top_k: int = 5,
    max_chunks: int = 5,
):
    """搜索 Memory Tree，并返回摘要路径和原始 chunks"""
    return await search_memory_tree(
        query=q,
        tree_type=tree_type,
        top_k=top_k,
        max_chunks=max_chunks,
    )


@app.get("/memory/tree/{node_id}")
async def memory_tree_node(node_id: str):
    """查询一个 Memory Tree 节点的直接子节点和 chunks"""
    return await get_memory_tree_node(node_id)


@app.get("/negotiate/stream")
async def negotiate_stream(request: Request):
    """SSE 实时流——监听 Agent 之间的通信"""

    async def event_stream():
        queue = asyncio.Queue()

        async def sse_listener(msg):
            await queue.put(msg)

        orchestrator.bus.add_listener(sse_listener)

        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=60)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",  #什么这是SSE协议
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
