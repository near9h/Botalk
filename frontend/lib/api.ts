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
  // RBAC 扩展
  owner_id?: number | null;
  scope?: "system" | "user";
  // 公开分享：私有 bot 标记后所有用户可见
  is_public?: boolean;
  // Wire-facing tokens of knowledge bases this bot has mounted.
  // Surfaced by `GET /api/bots` and editable via PATCH /api/bots/{id}.
  // KB rows on the server still link via integer FK (`kb_ids`); we
  // keep that list around for callers that want to follow the join,
  // but the URL/UI surface uses `kb_public_ids` exclusively.
  kb_public_ids?: string[];
  kb_ids?: number[];
  created_at: string;
};

export type Group = {
  // 注意：整数 id 不再对外暴露；只暴露 public_id。路由 / 状态用这个。
  public_id: string;
  name: string;
  description: string | null;
  mode: "round_robin" | "auto" | "manual";
  max_rounds: number;
  bot_ids: number[];
  // RBAC 扩展
  owner_id?: number | null;
  owner_username?: string | null;
  scope?: "system" | "user";
  // 群级「群通知 / 群规」追加文本。平台级规则见 GroupPolicy，
  // 注入时平台规则始终在前且不可被 notice 覆盖。
  notice: string;
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
  // public_ids of bot-authored attachments surfaced by this message.
  attachments: string[];
  // Stage 3 / Stage 4: KB citations persisted alongside the message so
  // /api/messages can re-render SourceCitation chips on page refresh
  // without re-running retrieval. Mirrors the SSE `cited_refs` payload.
  cited_refs?: CitedRef[];
  created_at: string;
};

export type Run = {
  id: number;
  group_id: number;
  status: string;
  title: string;
  // Opaque random token used in shared URLs (`/group/{gid}?task=<token>`)
  // instead of the internal integer id, so a recipient doesn't see or
  // guess at the task volume of this group.
  share_token: string;
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

// ──────────────────── knowledge base (Stage 1-5) ────────────────────
//
// CitedRef is the citation metadata attached to a bot reply when the
// orchestrator injected KB context into the prompt. The chat layer
// forwards it via SSE `cited_refs` and persists it on the message row
// so /api/messages can re-render the chips without re-running retrieval.
//
// KnowledgeBase is the KB itself (CRUD via /api/kb). KbDocument is one
// ingested source file. KbChunk is one retrieval hit — what the PDF
// viewer overlays a bbox on top of.

export type CitedRef = {
  chunk_id: number;
  // Wire-facing KB token. Mirrors `KnowledgeBase.public_id`; the
  // chat UI uses this to fetch `/api/kb/{public_id}/chunks/{id}`.
  kb_id: string;
  kb_doc_id: number;
  filename: string;
  page: number | null;
  para: number | null;
  bbox: [number, number, number, number] | null;
  snippet: string;
  score: number;
  ragflow_chunk_id: string | null;
  // Pre-formatted `[doc: filename p.X ¶Y]` key from the backend so the
  // markdown renderer can match without re-parsing the filename.
  citation_key: string;
};

export type KnowledgeBase = {
  // Integer PK — kept around for the KB list sort + debugging.
  // Wire-facing routes should use `public_id` exclusively.
  id: number;
  public_id: string;
  name: string;
  description: string | null;
  is_public: boolean;
  ragflow_dataset_id: string | null;
  // Number of documents that finished ingest (status="ready"). Drives
  // the "本地检索就绪" badge in the KB list + detail page.
  ready_doc_count?: number;
  created_at: string;
};

export type KbDocument = {
  id: number;
  kb_id: number;
  attachment_id: number;
  // wire-facing id used by /api/attachments/{public_id}/download. KB
  // uploads made before the public_id migration may still come back
  // null — fall back to attachment_id in that case (legacy downloads
  // stopped working with the migration).
  public_id?: string | null;
  filename: string;
  mime_type: string;
  size_bytes: number;
  // pending | parsing | ready | failed
  status: string;
  error: string;
  chunk_count: number;
  ragflow_doc_id: string | null;
  created_at: string;
};

export type KbChunk = {
  id: number;
  kb_doc_id: number;
  ragflow_chunk_id: string | null;
  page: number | null;
  para: number | null;
  bbox_json: number[] | null;
  snippet: string;
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

export type GeneratePersonaResult = {
  persona: string;
  model: string;
  latency_ms: number;
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

export type User = {
  id: number;
  username: string;
  display_name?: string | null;
  email: string | null;
  role: "admin" | "user";
  status: "active" | "disabled";
  created_by_id?: number | null;
  last_login_at?: string | null;
  created_at: string;
};

export type AuditLog = {
  id: number;
  occurred_at: string;
  actor_id: number | null;
  actor_name: string;
  actor_role: string;
  action: string;
  target_type: string;
  target_id: string | null;
  target_name: string | null;
  ip: string | null;
  user_agent: string | null;
  status: "success" | "failure";
  detail: Record<string, unknown>;
};

// ──────────────────── 平台群规 / 防火墙规则 ────────────────────

export type PolicyRule = {
  id?: string | null;
  title: string;
  content: string;
  enabled: boolean;
};

export type GroupPolicy = {
  enabled: boolean;
  rules: PolicyRule[];
  // 后端用与注入完全相同的渲染逻辑算出的「平台群规段」文本。
  // 管理页直接展示它，无需前端复刻渲染规则。无规则时为 null。
  preview: string | null;
  updated_at: string | null;
  updated_by_username: string | null;
};

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
  createBot: (
    body: Omit<Bot, "id" | "created_at" | "is_system" | "is_protected" | "owner_id" | "scope"> & {
      scope?: "system" | "user";
    },
  ) => request<Bot>("/api/bots", { method: "POST", body: JSON.stringify(body) }),
  updateBot: (id: number, body: Partial<Bot>) =>
    request<Bot>(`/api/bots/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteBot: (id: number) =>
    request<void>(`/api/bots/${id}`, { method: "DELETE" }),

  listGroups: () => request<Group[]>("/api/groups"),
  createGroup: (
    body: Omit<
      Group,
      "public_id" | "created_at" | "owner_id" | "scope" | "notice"
    > & {
      scope?: "system" | "user";
      // 群级群规（创建时可选）。
      notice?: string;
    },
  ) =>
    request<Group>("/api/groups", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getGroup: (publicId: string) => request<Group>(`/api/groups/${publicId}`),
  updateGroup: (publicId: string, body: Partial<Group>) =>
    request<Group>(`/api/groups/${publicId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  addMember: (publicId: string, botId: number) =>
    request<Group>(`/api/groups/${publicId}/members/${botId}`, { method: "POST" }),
  removeMember: (publicId: string, botId: number) =>
    request<void>(`/api/groups/${publicId}/members/${botId}`, { method: "DELETE" }),
  deleteGroup: (publicId: string) =>
    request<void>(`/api/groups/${publicId}`, { method: "DELETE" }),

  listMessages: (groupPublicId: string, runId?: number) =>
    request<Message[]>(
      `/api/messages?group_public_id=${encodeURIComponent(groupPublicId)}${
        runId != null ? `&run_id=${runId}` : ""
      }`,
    ),
  listRuns: (groupPublicId: string) =>
    request<Run[]>(`/api/runs?group_public_id=${encodeURIComponent(groupPublicId)}`),
  listTasks: (groupPublicId: string) =>
    request<Run[]>(`/api/tasks?group_public_id=${encodeURIComponent(groupPublicId)}`),
  openTask: (groupPublicId: string, title?: string) =>
    request<Run>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ group_public_id: groupPublicId, title }),
    }),

  // 用户管理（admin-only）
  listUsers: () => request<User[]>("/api/users"),
  createUser: (body: {
    username: string;
    password?: string;
    display_name?: string;
    email?: string;
    role?: "admin" | "user";
  }) => request<User>("/api/users", { method: "POST", body: JSON.stringify(body) }),
  updateUser: (id: number, body: Partial<Pick<User, "display_name" | "email" | "role" | "status">>) =>
    request<User>(`/api/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  resetUserPassword: (id: number) =>
    request<{ username: string; new_password: string }>(
      `/api/users/${id}/reset-password`,
      { method: "POST" },
    ),
  changeUserPassword: (
    id: number,
    body: { old_password: string; new_password: string },
  ) =>
    request<{ username: string; new_password: string }>(
      `/api/users/${id}/change-password`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  enableUser: (id: number) =>
    request<User>(`/api/users/${id}/enable`, { method: "POST" }),
  disableUser: (id: number) =>
    request<unknown>(`/api/users/${id}`, { method: "DELETE" }),

  // 审计日志（admin-only）
  listAuditLogs: (params: {
    actor_id?: number;
    actor_role?: string;
    action?: string;
    target_type?: string;
    target_id?: string;
    status?: string;
    ip?: string;
    from?: string;
    to?: string;
    limit?: number;
    offset?: number;
  } = {}) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
    });
    const qs = q.toString();
    return request<{
      items: AuditLog[];
      total: number;
      limit: number;
      offset: number;
    }>(`/api/audit/logs${qs ? `?${qs}` : ""}`);
  },
  getAuditStats: () =>
    request<{ total_last_24h: number; by_action: Array<{ action: string; count: number }>; by_actor: Array<{ actor: string; count: number }> }>(
      "/api/audit/stats",
    ),

  // 平台群规 / 防火墙规则。读：所有登录用户；写：仅管理员。
  getPolicy: () => request<GroupPolicy>("/api/policies"),
  updatePolicy: (body: { enabled: boolean; rules: PolicyRule[] }) =>
    request<GroupPolicy>("/api/policies", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  // Tasks (user-facing alias of Runs): one task = one user turn + the
  // multi-bot reply it triggered. The chat UI binds every message to
  // exactly one task; "新会话" creates a new pending task, history
  // drawer reopens an existing task by id or share_token.
  getTask: (taskIdOrToken: number | string) =>
    request<Task>(`/api/tasks/${taskIdOrToken}`),
  renameTask: (taskIdOrToken: number | string, title: string) =>
    request<Task>(`/api/tasks/${taskIdOrToken}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteTask: (taskIdOrToken: number | string) =>
    request<void>(`/api/tasks/${taskIdOrToken}`, { method: "DELETE" }),

  clearMessages: (groupPublicId: string) =>
    request<void>(
      `/api/messages?group_public_id=${encodeURIComponent(groupPublicId)}`,
      { method: "DELETE" },
    ),
  listModels: () => request<{ data: ModelInfo[]; cached: boolean }>("/api/models"),
  testModel: (body: { model: string; prompt?: string; temperature?: number }) =>
    request<ModelTestResult>("/api/models/test", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  generatePersona: (body: { name: string; hint?: string }) =>
    request<GeneratePersonaResult>("/api/bots/generate-persona", {
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
  installCommunity: (body: { url: string; transport?: string; name?: string; description?: string; source?: string }) =>
    request<Skill>("/api/skills/community/install", {
      method: "POST",
      body: JSON.stringify(body),
    }),
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
  batchAttachmentMeta: (publicIds: string[]) =>
    request<AttachmentMeta[]>("/api/attachments/batch-meta", {
      method: "POST",
      body: JSON.stringify(publicIds),
    }),
  uploadAttachment: (file: File, groupPublicId?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (groupPublicId != null) fd.append("group_public_id", groupPublicId);
    return fetch(`${API_BASE}/api/attachments`, {
      method: "POST",
      body: fd,
      credentials: "include",
    }).then(async (r) => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
      return (await r.json()) as Attachment;
    });
  },

  // ── Knowledge bases (Stage 5) ──
  // CRUD wrappers for /api/kb. Uploads use FormData (multipart) so we
  // can't reuse the JSON `request` helper; instead each upload path
  // builds its own fetch.
  listKbs: () => request<KnowledgeBase[]>("/api/kb"),
  createKb: (body: { name: string; description?: string; is_public?: boolean }) =>
    request<KnowledgeBase>("/api/kb", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getKb: (kbId: string) => request<KnowledgeBase>(`/api/kb/${kbId}`),
  deleteKb: (kbId: string) =>
    request<void>(`/api/kb/${kbId}`, { method: "DELETE" }),
  listKbDocuments: (kbId: string) =>
    request<KbDocument[]>(`/api/kb/${kbId}/documents`),
  getKbDocument: (kbId: string, docId: number) =>
    request<KbDocument>(`/api/kb/${kbId}/documents/${docId}`),
  deleteKbDocument: (kbId: string, docId: number) =>
    request<void>(`/api/kb/${kbId}/documents/${docId}`, {
      method: "DELETE",
    }),
  getKbChunk: (kbId: string, chunkId: number) =>
    request<KbChunk>(`/api/kb/${kbId}/chunks/${chunkId}`),
  // Stage 5 fix: per-doc chunk listing (drives the KB-detail page's
  // chunk preview). Added in the same backend route pass as the
  // single-chunk endpoint; the route is order-sensitive so the
  // server-side docstring explains why.
  listKbDocumentChunks: (kbId: string, docId: number) =>
    request<KbChunk[]>(`/api/kb/${kbId}/documents/${docId}/chunks`),
  uploadKbDocument: (kbId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`${API_BASE}/api/kb/${kbId}/documents`, {
      method: "POST",
      body: fd,
      credentials: "include",
    }).then(async (r) => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
      return (await r.json()) as KbDocument;
    });
  },
};

export type Attachment = {
  id: number;
  // Unguessable download token (see Attachment.public_id on backend).
  public_id: string;
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
  // Backend integer PK; opaque to the UI, kept for callers that need it
  // for internal joins. URLs in the UI always use `public_id`.
  id: number;
  // Unguessable token used in `/api/attachments/<public_id>/download`
  // and `attachment://<public_id>` markdown links. Replaces the
  // integer id so URLs aren't enumerable.
  public_id: string;
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
        // Stage 3: KB citation metadata. Always present (possibly `[]`)
        // for `bot`/`summary` messages; absent for `user`/`system` events.
        cited_refs?: CitedRef[];
      };
    }
  | { event: "tool_call"; data: { bot_id: number | null; tool_name: string; tool_args?: Record<string, unknown> } }
  | { event: "run_end"; data: { run_id: number | null } }
  | { event: "error"; data: { error: string } };

export function streamChat(
  body: {
    group_public_id: string;
    prompt: string;
    attachment_ids?: string[];
    // Append this prompt into an existing task instead of opening a new
    // one. The chat UI calls POST /api/tasks up front when the user
    // hits "新会话", then includes the returned token here so the first
    // message lands in that exact task (instead of a backend-allocated
    // one the UI doesn't know about). Sending task_id (integer) is also
    // supported for legacy callers.
    task_token?: string;
    task_id?: number;
  },
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
        // Parse SSE: `event:` / `data:` lines separated by a blank line.
        // Per the SSE spec (and sse-starlette's default), each line ends
        // with CRLF and events are separated by a blank CRLF — i.e. the
        // on-wire boundary is "\r\n\r\n". The earlier "\n\n" split missed
        // the "\r" and silently dropped every event on the floor: the
        // buffer grew forever and the UI only "saw" the chat reply after
        // a manual page refresh (which re-reads from the DB). Match both
        // "\r\n\r\n" and "\n\n" so we stay compatible with any future
        // backend that swaps the separator.
        let idx: number;
        // eslint-disable-next-line no-cond-assign
        while ((idx = buf.search(/\r\n\r\n|\n\n/)) >= 0) {
          const sepLen = buf.startsWith("\r\n\r\n", idx) ? 4 : 2;
          const chunk = buf.slice(0, idx);
          buf = buf.slice(idx + sepLen);
          // Strip trailing "\r" from each line so "event: foo\r" still
          // matches the `event:` / `data:` prefixes.
          const lines = chunk.split("\n").map((l) =>
            l.endsWith("\r") ? l.slice(0, -1) : l,
          );
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
      // 用户点击「停止」触发的 abort 不是错误，避免显示
      // "BodyStreamBuffer was aborted" 这类技术性提示。
      if (ctrl.signal.aborted) return;
      onEvent("error", { error: e instanceof Error ? e.message : String(e) });
    });
  return () => ctrl.abort();
}

// ──────────────────── model vendor helpers ────────────────────

export function vendorOfModelId(id: string | null | undefined): string {
  // Defensive: a bot row missing a model id used to crash here with
  // "Cannot read properties of undefined (reading 'toLowerCase')".
  const m = (id ?? "").toLowerCase();
  if (!m) return "other";
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
