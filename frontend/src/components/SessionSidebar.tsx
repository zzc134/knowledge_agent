"use client";

import { SavedSession } from "@/lib/storage";

export default function SessionSidebar({
  sessions,
  activeId,
  onSelect,
  onNew,
  onDelete,
}: {
  sessions: SavedSession[];
  activeId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}) {
  return (
    <aside className="w-64 bg-gray-900 text-gray-200 flex flex-col shrink-0">
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-sm font-bold text-white">Knowledge Agent</h1>
        <p className="text-xs text-gray-400 mt-1">多 Agent 知识管理</p>
      </div>

      <button
        onClick={onNew}
        className="mx-3 mt-3 px-3 py-2 text-sm bg-gray-800 hover:bg-gray-700 rounded-lg text-left transition"
      >
        + 新对话
      </button>

      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        {sessions.map((s) => (
          <div
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={`group flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer text-sm transition ${
              s.id === activeId
                ? "bg-gray-700 text-white"
                : "hover:bg-gray-800 text-gray-400"
            }`}
          >
            <span className="truncate">{s.title}</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete(s.id);
              }}
              className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 transition ml-2 shrink-0"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </aside>
  );
}
