"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { chat, Message } from "@/lib/api";
import {
  loadSessions,
  saveSession,
  deleteSession,
  type SavedSession,
  type SavedMessage,
} from "@/lib/storage";
import SessionSidebar from "@/components/SessionSidebar";
import AgentMonitor from "@/components/AgentMonitor";
import AgentStatusBar from "@/components/AgentStatusBar";

function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

export default function Home() {
  const [sessions, setSessions] = useState<SavedSession[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [latestBusMsg, setLatestBusMsg] = useState<Message>();
  const historyEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = loadSessions();
    setSessions(saved);
    if (saved.length > 0) setActiveId(saved[0].id);
  }, []);

  const persist = useCallback(
    (id: string, msgs: SavedMessage[]) => {
      const existing = sessions.find((s) => s.id === id);
      const updated: SavedSession = {
        id,
        title:
          msgs.find((m) => m.role === "user")?.content?.slice(0, 30) ||
          existing?.title ||
          "新对话",
        messages: msgs,
        createdAt: existing?.createdAt || Date.now(),
        updatedAt: Date.now(),
      };
      saveSession(updated);
      setSessions((prev) => {
        const rest = prev.filter((s) => s.id !== id);
        return [...rest, updated];
      });
    },
    [sessions]
  );

  const activeSession = activeId ? sessions.find((s) => s.id === activeId) : null;
  const messages = activeSession?.messages || [];

  useEffect(() => {
    historyEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSend = async () => {
    if (!message.trim()) return;
    const userMsg = message;
    setMessage("");

    const sid = activeId || generateId();
    if (!activeId) setActiveId(sid);

    const userEntry: SavedMessage = {
      role: "user",
      content: userMsg,
      timestamp: Date.now(),
    };
    const currentMsgs = activeId === sid ? messages : [];
    const newMsgs = [...currentMsgs, userEntry];
    persist(sid, newMsgs);

    setLoading(true);
    try {
      const result = await chat(userMsg);
      const agentEntry: SavedMessage = {
        role: "agent",
        content: result.response,
        agent: result.agent,
        timestamp: Date.now(),
      };
      persist(sid, [...newMsgs, agentEntry]);
    } catch (e) {
      const errEntry: SavedMessage = {
        role: "agent",
        content: `请求失败: ${e}`,
        agent: "error",
        timestamp: Date.now(),
      };
      persist(sid, [...newMsgs, errEntry]);
    }
    setLoading(false);
  };

  return (
    <div className="flex h-screen bg-gray-50">
      <SessionSidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={() => setActiveId("")}
        onDelete={(id) => {
          deleteSession(id);
          setSessions((prev) => prev.filter((s) => s.id !== id));
          if (id === activeId) setActiveId("");
        }}
      />

      <main className="flex-1 flex flex-col min-w-0">
        <AgentStatusBar latestMessage={latestBusMsg} />

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {messages.length === 0 && !loading && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center text-gray-400">
                <p className="text-lg mb-2">知识管理助手</p>
                <p className="text-sm">输入问题开始对话，或者粘贴 URL 收藏文章</p>
              </div>
            </div>
          )}
          {messages.map((entry, i) => (
            <div
              key={i}
              className={`flex ${entry.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[75%] rounded-lg p-4 ${
                  entry.role === "user"
                    ? "bg-blue-600 text-white"
                    : "bg-white shadow text-gray-800"
                }`}
              >
                {entry.agent && (
                  <div className="text-xs text-gray-500 mb-1">由 {entry.agent} 回答</div>
                )}
                <div className="whitespace-pre-wrap leading-relaxed text-sm">
                  {entry.content}
                </div>
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-white shadow rounded-lg p-4 text-gray-400 text-sm">
                <span className="animate-pulse">思考中...</span>
              </div>
            </div>
          )}
          <div ref={historyEnd} />
        </div>

        <div className="border-t bg-white px-6 py-4">
          <div className="max-w-3xl mx-auto flex gap-3">
            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
              placeholder="输入问题，或者粘贴 URL..."
              className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              disabled={loading}
            />
            <button
              onClick={handleSend}
              disabled={loading}
              className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 transition"
            >
              发送
            </button>
          </div>
        </div>
      </main>

      <div className="w-80 bg-white border-l border-gray-200 p-4 overflow-y-auto shrink-0">
        <AgentMonitor onMessage={setLatestBusMsg} />
      </div>
    </div>
  );
}
