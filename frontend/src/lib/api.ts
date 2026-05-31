const BASE_URL = "http://localhost:8000";



定义类型
export interface ChatResponse {
  agent: string;
  response: string;
  tool_calls: { tool: string; params: Record<string, string>; result: string }[];
  session_id: string;
}

export interface NegotiateResponse {
  task: string;
  final_answer: string;
  message_history: Message[];
}

export interface Message {
  from_agent: string;
  to_agent: string;
  msg_type: string;
  content: string;
  round_num: number;
}

export async function chat(message: string): Promise<ChatResponse> {
  const res = await fetch(`${BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return res.json();
}

export async function negotiate(task: string): Promise<NegotiateResponse> {
  const res = await fetch(`${BASE_URL}/negotiate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task }),
  });
  return res.json();
}
