"use client";

import { useState, useRef } from "react";

export default function DocumentUpload({ onUpload }: { onUpload?: () => void }) {
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    const text = await file.text();
    const res = await fetch("http://localhost:8000/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: `请保存以下文档：\n标题：${file.name}\n\n内容：\n${text.slice(0, 5000)}`,
      }),
    });
    if (res.ok) onUpload?.();
  };

  return (
    <div
      className={`border-2 border-dashed rounded-lg p-6 text-center text-sm transition ${
        dragOver ? "border-blue-400 bg-blue-50" : "border-gray-300"
      }`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const file = e.dataTransfer.files[0];
        if (file) handleFile(file);
      }}
      onClick={() => fileRef.current?.click()}
    >
      <input
        ref={fileRef}
        type="file"
        accept=".md,.txt,.html,.json"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
        }}
      />
      <p className="text-gray-500">
        拖拽文件到此处上传，或点击选择文件
      </p>
      <p className="text-gray-400 text-xs mt-1">
        支持 Markdown / TXT / HTML
      </p>
    </div>
  );
}
