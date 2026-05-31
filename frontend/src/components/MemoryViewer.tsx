"use client";

import { useState, useEffect } from "react";

interface Interest {
  topic: string;
  confidence: number;
  memory_type: string;
  access_count: number;
}

export default function MemoryViewer() {
  const [interests, setInterests] = useState<Interest[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("http://localhost:8000/memory/interests")
      .then((r) => r.json())
      .then((data) => setInterests(data.interests || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-xs text-gray-400">加载中...</p>;

  return (
    <div className="text-sm">
      <h3 className="font-semibold text-gray-700 mb-2">长期记忆</h3>
      {interests.length === 0 ? (
        <p className="text-xs text-gray-400">暂无记录</p>
      ) : (
        <div className="space-y-2">
          {interests.map((item) => (
            <div
              key={item.topic}
              className="flex items-center justify-between bg-gray-50 rounded px-3 py-2"
            >
              <div>
                <span className="font-medium text-gray-700">{item.topic}</span>
                <span className="ml-2 text-xs bg-gray-200 px-1.5 py-0.5 rounded text-gray-500">
                  {item.memory_type === "factual" ? "事实" : "偏好"}
                </span>
              </div>
              <div className="text-right">
                <div className="text-xs text-gray-500">
                  置信度: {(item.confidence * 100).toFixed(0)}%
                </div>
                <div className="text-xs text-gray-400">
                  访问 {item.access_count} 次
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
