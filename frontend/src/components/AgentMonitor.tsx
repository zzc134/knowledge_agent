"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { Message } from "@/lib/api";

export default function AgentMonitor({
  onMessage,
}: {
  onMessage?: (msg: Message) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [connected, setConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const startListening = useCallback(() => {
    if (eventSourceRef.current) return;

    setConnected(true);
    const es = new EventSource("http://localhost:8000/negotiate/stream");
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setMessages((prev) => [...prev, data]);
      onMessage?.(data);
    };

    es.onerror = () => {
      setConnected(false);
      es.close();
      eventSourceRef.current = null;
      setTimeout(() => startListening(), 3000);
    };
  }, [onMessage]);

  useEffect(() => {
    startListening();
    return () => {
      eventSourceRef.current?.close();
    };
  }, [startListening]);

  const agentColors: Record<string, string> = {
    orchestrator: "bg-gray-500",
    collector: "bg-green-500",
    curator: "bg-purple-500",
    librarian: "bg-blue-500",
    editor: "bg-orange-500",
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-700">Agent 监控</h2>
        <span
          className={`w-2 h-2 rounded-full ${
            connected ? "bg-green-400 animate-pulse" : "bg-gray-300"
          }`}
        />
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto text-xs">
        {messages.length === 0 && connected && (
          <p className="text-gray-400">等待 Agent 通信...</p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className="flex items-start gap-2 animate-fade-in">
            <span
              className={`inline-block w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                agentColors[msg.from_agent] || "bg-gray-400"
              }`}
            />
            <div>
              <span className="font-medium text-gray-700">{msg.from_agent}</span>
              <span className="text-gray-400 mx-1">→</span>
              <span className="font-medium text-gray-700">{msg.to_agent}</span>
              <span className="ml-2 text-xs bg-gray-100 px-1.5 py-0.5 rounded text-gray-500">
                {msg.msg_type}
              </span>
              <p className="text-gray-600 mt-0.5 line-clamp-3">{msg.content}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
