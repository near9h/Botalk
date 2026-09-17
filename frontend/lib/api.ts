// Same-origin by default — the nginx reverse proxy forwards /api/* to the
// backend container, so the browser only ever talks to the host it loaded
// from. This means it doesn't matter whether the user hits the app via
// http://localhost:3500, http://192.168.x.x:3500, or a public hostname —
// API calls always go to the same origin.
//
// To bypass the proxy and talk to the backend directly (e.g. for local
// dev with separate ports), set NEXT_PUBLIC_API_BASE=http://localhost:8000.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const _proc: any = (globalThis as any).process ?? { env: {} };
export const API_BASE = _proc.env?.NEXT_PUBLIC_API_BASE || "";

export type Bot = {
  id: number;
  name: string;
  avatar_url: string | null;
  emoji: string;
  persona: string;
  model: string;
  temperature: number;
  params: Record<string, unknown>;
  // System-managed bots (e.g. the summarizer) can't be deleted and
  // can't have their name/model changed.
  is_system: boolean;
  is_protected?: boolean;
  created_at: string;
};

export type Group = {
  id: number;
  name: string;
  description: string | null;
  mode: "round_robin" | "auto" | "manual";
  max_rounds: number;
  bot_ids: number[];
  created_at: string;
};

export type Message = {
  id: number;
  run_id: number | null;
  group_id: number;
  role: "user" | "bot" | "system";
  bot_id: number | null;
  content: string;
  token_usage: number;
  attachments: number[];
  created_at: string;
};

export type Run = {
  id: number;
  group_id: number;
  status: string;
  title: string;
  started_at: string;
  finished_at: string | null;
  total_tokens: number;
  user_prompt: string;
  message_count: number;
};

// User-facing alias: a "task" is exactly one Run row, but the chat UI
// treats it as a self-contained conversation thread (one user turn + the
// multi-bot reply). Keeping the type structurally identical to `Run` so
// the two can be used interchangeably.
export type Task = Run;

export type ModelInfo = {
  id: string;
  owned_by: string;
  vendor: string;
};

export type Skill = {
  id: number;
  key: string;
  name: string;
  description: string;
  type: "knowledge" | "tool" | "mcp";
  category: string;
  icon: string;
  manifest: Record<string, unknown>;
  config_schema: Record<string, unknown>;
  builtin: boolean;
  created_at: string;
  bot_count?: number;
};

export type SkillAsset = {
  id: string;
  name: string;
  description: string;
  content_md: string;
  is_default: boolean;
};

export type BotSkill = {
  skill: Skill;
  config: Record<string, unknown>;
  enabled: boolean;
};

export type ModelTestResult = {
  ok: boolean;
  model: string;
  reply: string | null;
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  error: string | null;
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
    // Send cookies on every request — required for the session cookie.
    credentials: init.credentials ?? "include",
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

export type User = { id: number; username: string; email: string | null };

export const api = {
  // Auth
  me: () => request<User | null>("/api/auth/me"),
  login: (username: string, password: string) =>
    request<User>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
      credentials: "include" as RequestCredentials,
    }),
  logout: () =>
    request<{ ok: boolean }>("/api/auth/logout", {
      method: "POST",
      credentials: "include" as RequestCredentials,
    }),

  listBots: () => request<Bot[]>("/api/bots"),
  // `is_protected` defaults server-side; allow callers to omit it.
  createBot: (body: Omit<Bot, "id" | "created_at" | "is_system" | "is_protected">) =>
    request<Bot>("/api/bots", { method: "POST", body: JSON.stringify(body) }),
  updateBot: (id: number, body: Partial<Bot>) =>
    request<Bot>(`/api/bots/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteBot: (id: number) =>
    request<void>(`/api/bots/${id}`, { method: "DELETE" }),

  listGroups: () => request<Group[]>("/api/groups"),
  createGroup: (body: Omit<Group, "id" | "created_at">) =>
    request<Group>("/api/groups", { method: "POST", body: JSON.stringify(body) }),
  getGroup: (id: number) => request<Group>(`/api/groups/${id}`),
  addMember: (groupId: number, botId: number) =>
    request<Group>(`/api/groups/${groupId}/members/${botId}`, { method: "POST" }),
  removeMember: (groupId: number, botId: number) =>
    request<void>(`/api/groups/${groupId}/members/${botId}`, { method: "DELETE" }),
  deleteGroup: (id: number) =>
    request<void>(`/api/groups/${id}`, { method: "DELETE" }),

  listMessages: (groupId: number, runId?: number) =>
    request<Message[]>(
      `/api/messages?group_id=${groupId}${runId != null ? `&run_id=${runId}` : ""}`,
    ),
  listRuns: (groupId: number) => request<Run[]>(`/api/runs?group_id=${groupId}`),

  // Tasks (user-facing alias of Runs): one task = one user turn + the
  // multi-bot reply it triggered. The chat UI binds every message to
  // exactly one task; "新会话" creates a new pending task, history
  // drawer reopens an existing task by id.
  listTasks: (groupId: number) =>
    request<Task[]>(`/api/tasks?group_id=${groupId}`),
  getTask: (taskId: number) =>
    request<Task>(`/api/tasks/${taskId}`),
  openTask: (groupId: number, title?: string) =>
    request<Task>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ group_id: groupId, title }),
    }),
  renameTask: (taskId: number, title: string) =>
    request<Task>(`/api/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteTask: (taskId: number) =>
    request<void>(`/api/tasks/${taskId}`, { method: "DELETE" }),

  clearMessages: (groupId: number) =>
    request<void>(`/api/messages?group_id=${groupId}`, { method: "DELETE" }),
  listModels: () => request<{ data: ModelInfo[]; cached: boolean }>("/api/models"),
  testModel: (body: { model: string; prompt?: string; temperature?: number }) =>
    request<ModelTestResult>("/api/models/test", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Skills
  listSkills: () => request<Skill[]>("/api/skills"),
  getSkill: (id: number) => request<Skill>(`/api/skills/${id}`),
  createSkill: (body: Partial<Skill>) =>
    request<Skill>("/api/skills", { method: "POST", body: JSON.stringify(body) }),
  updateSkill: (id: number, body: Partial<Skill>) =>
    request<Skill>(`/api/skills/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSkill: (id: number) =>
    request<void>(`/api/skills/${id}`, { method: "DELETE" }),
  importSkillMdFile: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`${API_BASE}/api/skills/import/skillmd`, {
      method: "POST",
      body: fd,
      credentials: "include",
    }).then(async (r) => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
      return (await r.json()) as Skill;
    });
  },
  importSkillMdUrl: (url: string, name?: string) =>
    request<Skill>("/api/skills/import/skillmd/url", {
      method: "POST",
      body: JSON.stringify({ url, name }),
    }),
  importMcp: (body: { url: string; transport: string; name?: string }) =>
    request<Skill>("/api/skills/import/mcp", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  communitySearch: (q: string) =>
    request<Array<Record<string, unknown>>>(`/api/skills/community/search?q=${encodeURIComponent(q)}`),
  uploadSkillAsset: (skillId: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`${API_BASE}/api/skills/${skillId}/assets`, {
      method: "POST",
      body: fd,
      credentials: "include",
    }).then(async (r) => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
      return (await r.json()) as Skill;
    });
  },
  updateSkillAsset: (skillId: number, assetId: string, body: Partial<SkillAsset>) =>
    request<Skill>(`/api/skills/${skillId}/assets/${assetId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteSkillAsset: (skillId: number, assetId: string) =>
    request<Skill>(`/api/skills/${skillId}/assets/${assetId}`, { method: "DELETE" }),

  // Bots ↔ Skills
  getBotSkills: (botId: number) =>
    request<BotSkill[]>(`/api/bots/${botId}/skills`),
  // Wire format matches the backend `BotSkillSet` schema
  // (`{ skill_ids: number[] }`). Per-skill `enabled` is implicit (all rows
  // we PUT are enabled); per-skill `config` is supported via the second
  // argument so callers can e.g. attach per-bot Tavily keys later without
  // another round-trip.
  setBotSkills: (
    botId: number,
    skillIds: number[],
    config?: Record<number, Record<string, unknown>>,
  ) =>
    request<BotSkill[]>(`/api/bots/${botId}/skills`, {
      method: "PUT",
      body: JSON.stringify({ skill_ids: skillIds, config: config ?? {} }),
    }),

  // Attachments
  listAttachments: (groupId?: number) =>
    request<AttachmentMeta[]>(
      `${API_BASE}/api/attachments${groupId != null ? `?group_id=${groupId}` : ""}`,
    ),
  batchAttachmentMeta: (ids: number[]) =>
    request<AttachmentMeta[]>("/api/attachments/batch-meta", {
      method: "POST",
      body: JSON.stringify(ids),
    }),
  uploadAttachment: (file: File, groupId?: number) => {
    const fd = new FormData();
    fd.append("file", file);
    if (groupId != null) fd.append("group_id", String(groupId));
    return fetch(`${API_BASE}/api/attachments`, {
      method: "POST",
      body: fd,
      credentials: "include",
    }).then(async (r) => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
      return (await r.json()) as Attachment;
    });
  },
};

export type Attachment = {
  id: number;
  group_id: number | null;
  filename: string;
  mime_type: string;
  size_bytes: number;
  status: string;
  err_msg: string | null;
  content_md: string;
  // Present in list payloads (small); absent in detail payloads.
  content_preview?: string;
  content_chars?: number;
  created_at: string;
};

// Bot-authored attachment metadata surfaced by the chat layer so the
// bubble can render a download card without a second fetch.
export type AttachmentMeta = {
  id: number;
  filename: string;
  mime_type: string;
  size_bytes: number;
  source: "user" | "bot";
};

// Used by the message list → renderMessageWithMentions cache primer.
export const _internal = { request };

// ──────────────────── chat streaming ────────────────────

export type ChatEvent =
  | { event: "user_message"; data: { id: number; content: string } }
  | { event: "run_start"; data: { prompt: string } }
  | {
      event: "message_start";
      data: { bot_id: number | null; bot_name: string | null; round_index?: number };
    }
  | { event: "token"; data: { bot_id: number | null; content: string } }
  | {
      event: "message_end";
      data: {
        bot_id: number | null;
        bot_name: string | null;
        content: string;
        round_index?: number;
        attachments?: AttachmentMeta[];
      };
    }
  | { event: "tool_call"; data: { bot_id: number | null; tool_name: string; tool_args?: Record<string, unknown> } }
  | { event: "run_end"; data: { run_id: number | null } }
  | { event: "error"; data: { error: string } };

export function streamChat(
  body: { group_id: number; prompt: string; attachment_ids?: number[] },
  onEvent: (event: string, data: Record<string, unknown>) => void,
): () => void {
  const ctrl = new AbortController();
  fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
    signal: ctrl.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) {
        onEvent("error", { error: `${res.status} ${res.statusText}` });
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        // Parse SSE: lines starting with `event: …` / `data: …` separated
        // by blank lines.
        let idx: number;
        // eslint-disable-next-line no-cond-assign
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const lines = chunk.split("\n");
          let ev: string | null = null;
          let data = "";
          for (const line of lines) {
            if (line.startsWith("event:")) ev = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (ev) {
            try {
              onEvent(ev, JSON.parse(data));
            } catch {
              onEvent(ev, { raw: data });
            }
          }
        }
      }
    })
    .catch((e) => {
      onEvent("error", { error: e instanceof Error ? e.message : String(e) });
    });
  return () => ctrl.abort();
}

// ──────────────────── model vendor helpers ────────────────────

export function vendorOfModelId(id: string): string {
  const m = id.toLowerCase();
  if (m.includes("gpt") || m.includes("o1") || m.includes("o3") || m.includes("o4") || m.includes("chatgpt")) return "openai";
  if (m.includes("claude")) return "anthropic";
  if (m.includes("gemini")) return "google";
  if (m.includes("deepseek")) return "deepseek";
  if (m.includes("qwen") || m.includes("qwq")) return "alibaba";
  if (m.includes("doubao")) return "doubao";
  if (m.includes("glm") || m.includes("chatglm")) return "zhipu";
  if (m.includes("llama")) return "meta";
  if (m.includes("mistral") || m.includes("mixtral")) return "mistral";
  if (m.includes("yi-")) return "yi";
  return "other";
}

const VENDOR_LABEL: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google",
  deepseek: "DeepSeek",
  alibaba: "Qwen",
  doubao: "Doubao",
  zhipu: "Zhipu",
  meta: "Llama",
  mistral: "Mistral",
  yi: "Yi",
  other: "Other",
};

export function vendorLabel(v: string): string {
  return VENDOR_LABEL[v] ?? v;
}
