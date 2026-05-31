"use client";

import { Message } from "@/lib/api";
import { useEffect, useState } from "react";

const agentLabels: Record<string, string> = {
  orchestrator: "协调器",
  collector: "收集员",
  curator: "分析员",
  librarian: "馆员",
  editor: "编辑",
};

export default function AgentStatusBar({
  latestMessage,
}: {
  latestMessage?: Message;
}) {
  const [status, setStatus] = useState("就绪");

  useEffect(() => {
    if (latestMessage) {
      const label = agentLabels[latestMessage.from_agent] || latestMessage.from_agent;
      setStatus(`${label} → ${agentLabels[latestMessage.to_agent] || latestMessage.to_agent}`);
      const timer = setTimeout(() => setStatus("就绪"), 3000);
      return () => clearTimeout(timer);
    }
  }, [latestMessage]);

  return (
    <div className="h-10 bg-white border-b border-gray-200 flex items-center px-6 shrink-0">
      <span className="text-xs text-gray-500">
        状态: <span className="text-gray-700 font-medium">{status}</span>
      </span>
    </div>
  );
}
