"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Avatar,
  avatarColor,
  Badge,
  Button,
  EmptyState,
  Select,
  useToast,
  vendorBadgeVariant,
} from "@/components/ui";
import { Sidebar } from "@/components/Sidebar";
import { ChatBubble, ChatBubbleData } from "@/components/ChatBubble";
import { Composer } from "@/components/Composer";
import { GroupWizard } from "@/components/GroupWizard";
import { api, Attachment, AttachmentMeta, Bot, Group, Message, Run, Task, streamChat, vendorLabel, vendorOfModelId } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function GroupPage({ params }: { params: { id: string } }) {
  const groupId = Number(params.id);
  const toast = useToast();
  const router = useRouter();
  const { t } = useI18n();

  const [group, setGroup] = useState<Group | null>(null);
  const [bots, setBots] = useState<Bot[]>([]);
  const [messages, setMessages] = useState<ChatBubbleData[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [activeSpeaker, setActiveSpeaker] = useState<number | null>(null);
  const [roundIndex, setRoundIndex] = useState(0);
  const [wizardOpen, setWizardOpen] = useState(false);
  // History: tasks = past conversation threads in this group.
  // activeTaskId = the task currently displayed in the main panel.
  // `null` means "no task selected yet" (initial loading state).
  const [tasks, setTasks] = useState<Task[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [activeTaskId, setActiveTaskId] = useState<number | null>(null);
  // Title of the currently-active task, for the header subtitle.
  const [activeTaskTitle, setActiveTaskTitle] = useState<string>("");
  const abortRef = useRef<(() => void) | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Initial view: group + bots + task list, then default to the latest
  // task (instead of "all messages across all tasks"). Showing every
  // task concatenated makes a refresh appear to "continue the previous
  // chat" — which was confusing after the user clicked "新会话".
  const loadAll = useCallback(async () => {
    try {
      const [g, b, taskList] = await Promise.all([
        api.getGroup(groupId),
        api.listBots(),
        api.listTasks(groupId),
      ]);
      setGroup(g);
      setBots(b);
      setTasks(taskList);
      const initialTaskId = taskList[0]?.id ?? null;
      setActiveTaskId(initialTaskId);
      setActiveTaskTitle(taskList[0]?.title || "");
      const hist = initialTaskId
        ? await api.listMessages(groupId, initialTaskId)
        : [];
      // Collect attachment IDs we need metadata for, then fetch in
      // one round-trip. Keeps the bubble cards rendered as soon as
      // history is loaded.
      const attIdSet = new Set<number>();
      hist.forEach((m: Message) =>
        (m.attachments ?? []).forEach((id: number) => attIdSet.add(id)),
      );
      let attMap = new Map<number, AttachmentMeta>();
      if (attIdSet.size > 0) {
        try {
          const metas = await api.batchAttachmentMeta(Array.from(attIdSet));
          attMap = new Map(metas.map((m) => [m.id, m]));
        } catch (e) {
          // Non-fatal — cards just won't show metadata.
          console.warn("batchAttachmentMeta failed", e);
        }
      }
      setMessages(
        hist.map((m: Message) => {
          const ids = m.attachments ?? [];
          const metas = ids
            .map((id) => attMap.get(id))
            .filter((x): x is AttachmentMeta => Boolean(x));
          return {
            id: `db-${m.id}`,
            role: m.role,
            botId: m.bot_id,
            botName: b.find((x) => x.id === m.bot_id)?.name ?? null,
            content: m.content,
            attachments: metas.length ? metas : undefined,
          };
        }),
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("common.toast.loadFail"), description: msg, variant: "error" });
    }
  }, [groupId, toast, t]);

  // Lightweight refresh (after member add/remove / new task / etc.):
  // re-fetch group, bots, and task list without disturbing the task
  // currently being viewed.
  const refresh = useCallback(async () => {
    try {
      const [g, b, taskList] = await Promise.all([
        api.getGroup(groupId),
        api.listBots(),
        api.listTasks(groupId),
      ]);
      setGroup(g);
      setBots(b);
      setTasks(taskList);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("common.toast.loadFail"), description: msg, variant: "error" });
    }
  }, [groupId, toast, t]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = (prompt: string, attachments: Attachment[]) => {
    if (streaming) return;
    const userBubble: ChatBubbleData = {
      id: makeId(),
      role: "user",
      content: prompt,
    };
    setMessages((prev) => [...prev, userBubble]);
    setStreaming(true);
    setRoundIndex(0);

    let currentBotId: number | null = null;
    let currentBotName: string | null = null;
    let currentBubbleId: string = "";

    const attachmentIds = attachments.map((a) => a.id);
    const rawAbort = streamChat(
      { group_id: groupId, prompt, attachment_ids: attachmentIds },
      (event, data) => {
        const d = data as Record<string, unknown>;
        switch (event) {
          case "message_start": {
            currentBotId = (d.bot_id as number) ?? null;
            currentBotName = (d.bot_name as string) ?? null;
            currentBubbleId = makeId();
            setActiveSpeaker(currentBotId);
            if (typeof d.round_index === "number") setRoundIndex(d.round_index);
            setMessages((prev) => [
              ...prev,
              {
                id: currentBubbleId,
                role: "bot",
                botId: currentBotId,
                botName: currentBotName,
                content: "",
                streaming: true,
              },
            ]);
            break;
          }
          case "token":
            if (currentBubbleId) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === currentBubbleId
                    ? { ...m, content: m.content + (d.content as string) }
                    : m,
                ),
              );
            }
            break;
          case "message_end": {
            // Backend now sends one message_end per bot, after a synchronous
            // completion — so a single round contains many (start, end)
            // pairs and we have to match by bot_id instead of a single
            // global currentBubbleId (which only tracks the latest one).
            const incomingBotId = (d.bot_id as number | null) ?? null;
            const incomingContent = (d.content as string) ?? "";
            // Backend now sends full attachment metadata (id+filename+size)
            // so the bubble can render the download card without a second
            // fetch. Older payloads (or absent field) leave it undefined.
            const incomingAtts = Array.isArray(d.attachments)
              ? (d.attachments as AttachmentMeta[])
              : undefined;
            setMessages((prev) =>
              prev.map((m) => {
                if (m.streaming && m.botId === incomingBotId) {
                  return {
                    ...m,
                    content: incomingContent || m.content,
                    streaming: false,
                    attachments: incomingAtts ?? m.attachments,
                  };
                }
                return m;
              }),
            );
            // Don't clear activeSpeaker here — `run_end` will do it. Clearing
            // per-bot would blank the sidebar highlight during the gap
            // between bots in the same round.
            break;
          }
          case "tool_call": {
            const toolName = (d.tool_name as string) || "tool";
            setMessages((prev) => [
              ...prev,
              {
                id: makeId(),
                role: "system",
                content: `🔧 ${toolName}`,
              },
            ]);
            break;
          }
          case "error":
            setMessages((prev) => [
              ...prev,
              {
                id: makeId(),
                role: "error",
                content: `${t("common.error")}：${(d.error as string) || t("common.error.unknown")}`,
              },
            ]);
            break;
          case "run_end":
            setStreaming(false);
            setActiveSpeaker(null);
            const finishedRunId = (d.run_id as number) ?? null;
            if (finishedRunId != null) setActiveRunId(finishedRunId);
            refresh(); // refresh the history session list (new run added)
            break;
        }
      },
    );

    // Failsafe: if the backend never sends run_end (e.g. dropped
    // connection, hung upstream), force-unlock the UI after 5 min so the
    // user isn't stuck on "● 正在讨论…" forever. The primary unlock is
    // the run_end event above.
    const unlockTimer = setTimeout(() => {
      setStreaming(false);
      setActiveSpeaker(null);
    }, 5 * 60 * 1000);
    abortRef.current = () => {
      clearTimeout(unlockTimer);
      rawAbort();
    };
  };

  const stop = () => {
    abortRef.current?.();
    setStreaming(false);
    setActiveSpeaker(null);
  };

  /** Open a past session from the history panel. */
  const selectRun = useCallback(
    async (runId: number) => {
      try {
        const hist = await api.listMessages(groupId, runId);
        setActiveRunId(runId);
        setMessages(
          hist.map((m: Message) => ({
            id: `db-${m.id}`,
            role: m.role,
            botId: m.bot_id,
            botName: bots.find((x) => x.id === m.bot_id)?.name ?? null,
            content: m.content,
          })),
        );
        setHistoryOpen(false);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        toast.push({ title: t("common.toast.loadFail"), description: msg, variant: "error" });
      }
    },
    [groupId, bots, toast, t],
  );

  /** Back to the latest-session view. (The "all sessions across runs"
   * concatenated view was removed because it confused users — a page
   * refresh made it look like the previous chat had resumed.) */
  const showAllMessages = useCallback(async () => {
    setHistoryOpen(false);
    await loadAll();
  }, [loadAll]);

  /**
   * Start a fresh session: only clears the local view. History stays in the
   * DB and remains reachable through the history panel.
   */
  const newSession = () => {
    if (streaming) {
      toast.push({ title: t("group.newSession.busy"), variant: "info" });
      return;
    }
    setActiveRunId(null);
    setMessages([]);
    setRoundIndex(0);
    setActiveSpeaker(null);
  };

  const addMember = async (botId: number) => {
    try {
      await api.addMember(groupId, botId);
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("common.toast.addFail"), description: msg, variant: "error" });
    }
  };

  const removeMember = async (botId: number) => {
    try {
      await api.removeMember(groupId, botId);
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("common.toast.removeFail"), description: msg, variant: "error" });
    }
  };

  const memberBots = useMemo(
    () => (group ? bots.filter((b) => group.bot_ids.includes(b.id)) : []),
    [bots, group],
  );
  const otherBots = useMemo(
    () => (group ? bots.filter((b) => !group.bot_ids.includes(b.id)) : []),
    [bots, group],
  );

  if (!group) {
    return (
      <div style={{ display: "flex", height: "100vh" }}>
        <Sidebar />
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--fg-subtle)" }}>
          {t("common.loading")}
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", height: "100vh", minHeight: 0, overflow: "hidden" }}>
      <Sidebar />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(260px, 320px) 1fr",
          flex: 1,
          minWidth: 0,
          minHeight: 0,
          // Inner messages panel needs a fixed-height parent for scroll to work.
          overflow: "hidden",
        }}
      >
        {/* Group sidebar (separate from global Sidebar, but matches its collapsed/expanded logic via flex) */}
        <aside
          className="glass"
          style={{
            borderRadius: 0,
            borderTop: 0,
            borderBottom: 0,
            borderLeft: 0,
            borderRight: "1px solid var(--border)",
            padding: 20,
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 20,
          }}
        >
          <div>
            <Link
              href="/"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontSize: 12,
                color: "var(--fg-muted)",
                marginBottom: 12,
              }}
            >
              {t("group.back")}
            </Link>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <Avatar emoji="💬" size={40} color={avatarColor(group.name)} />
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 16, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {group.name}
                </div>
                <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginTop: 2 }}>
                  {t("group.membersCount", { n: memberBots.length, r: roundIndex + 1 })}
                </div>
              </div>
            </div>
            {group.description && (
              <div
                style={{
                  fontSize: 12,
                  color: "var(--fg-muted)",
                  marginTop: 12,
                  padding: 10,
                  background: "var(--surface-2)",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--border)",
                  lineHeight: 1.5,
                }}
              >
                {group.description}
              </div>
            )}
            <div style={{ marginTop: 12, display: "flex", gap: 6 }}>
              <Badge variant={group.mode === "auto" ? "auto" : group.mode === "manual" ? "manual" : "round_robin"}>
                {t(`group.mode.${group.mode}`)}
              </Badge>
              <Badge variant="info">{t("group.rounds", { n: group.max_rounds })}</Badge>
            </div>
          </div>

          <div>
            <div
              style={{
                fontSize: 11,
                color: "var(--fg-subtle)",
                textTransform: "uppercase",
                letterSpacing: 0.5,
                marginBottom: 8,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <span>{t("group.members")}</span>
              <span style={{ color: "var(--accent)" }}>{memberBots.length}</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {memberBots.length === 0 ? (
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--fg-subtle)",
                    padding: 12,
                    background: "var(--surface-2)",
                    borderRadius: "var(--radius-sm)",
                    textAlign: "center",
                    border: "1px dashed var(--border-strong)",
                  }}
                >
                  {t("group.noMembers")}
                </div>
              ) : (
                memberBots.map((b) => {
                  const speaking = activeSpeaker === b.id;
                  return (
                    <div
                      key={b.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        padding: 8,
                        borderRadius: "var(--radius)",
                        background: speaking
                          ? "rgba(167, 139, 250, 0.10)"
                          : "var(--surface-2)",
                        border: speaking
                          ? "1px solid rgba(167, 139, 250, 0.30)"
                          : "1px solid var(--border)",
                        transition: "all var(--transition)",
                      }}
                    >
                      <div style={{ position: "relative" }}>
                        <Avatar emoji={b.emoji} size={32} color={avatarColor(b.name)} />
                        {speaking && (
                          <div
                            style={{
                              position: "absolute",
                              inset: -2,
                              borderRadius: "50%",
                              border: "2px solid var(--accent)",
                              animation: "pulse-ring 1.6s infinite",
                              pointerEvents: "none",
                            }}
                          />
                        )}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 500 }}>{b.name}</div>
                        <Badge variant={vendorBadgeVariant(vendorOfModelId(b.model))} style={{ fontSize: 10 }}>
                          {vendorLabel(vendorOfModelId(b.model))}
                        </Badge>
                      </div>
                      <button
                        onClick={() => removeMember(b.id)}
                        title={t("group.remove")}
                        style={{
                          width: 24,
                          height: 24,
                          borderRadius: 6,
                          color: "var(--fg-subtle)",
                          fontSize: 14,
                          transition: "all var(--transition)",
                        }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLButtonElement).style.background = "var(--danger-bg)";
                          (e.currentTarget as HTMLButtonElement).style.color = "var(--danger)";
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLButtonElement).style.background = "transparent";
                          (e.currentTarget as HTMLButtonElement).style.color = "var(--fg-subtle)";
                        }}
                      >
                        ×
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {otherBots.length > 0 && (
            <div>
              <div
                style={{
                  fontSize: 11,
                  color: "var(--fg-subtle)",
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                  marginBottom: 8,
                }}
              >
                {t("group.addBot")}
              </div>
              <Select
                value=""
                onChange={(v) => {
                  const n = Number(v);
                  if (n) addMember(n);
                }}
                placeholder={t("group.addBotPlaceholder")}
                options={otherBots.map((b) => ({
                  value: String(b.id),
                  label: `${b.emoji} ${b.name}`,
                  badge: (
                    <Badge variant={vendorBadgeVariant(vendorOfModelId(b.model))} style={{ fontSize: 10 }}>
                      {b.model}
                    </Badge>
                  ),
                }))}
              />
            </div>
          )}
        </aside>

        {/* Main chat */}
        <section
          style={{
            display: "flex",
            flexDirection: "column",
            minWidth: 0,
            // Critical: without min-height: 0 the flex child would refuse to
            // shrink below its content size, breaking the inner scroll.
            minHeight: 0,
            height: "100%",
            overflow: "hidden",
            background: "rgba(255, 255, 255, 0.30)",
            backdropFilter: "blur(40px)",
          }}
        >
          {/* Header (pinned to top; never scrolls with messages) */}
          <div
            style={{
              padding: "16px 24px",
              borderBottom: "1px solid var(--border)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              background: "var(--surface-2)",
              flexShrink: 0,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <Avatar emoji="💬" size={36} color={avatarColor(group.name)} />
              <div>
                <div style={{ fontSize: 15, fontWeight: 600 }}>{group.name}</div>
                <div style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
                  {streaming ? (
                    <span style={{ color: "var(--accent)" }}>
                      {t("group.header.discussing", { n: memberBots.length })}
                    </span>
                  ) : (
                    <span>{t("group.header.idle", { n: memberBots.length })}</span>
                  )}
                </div>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setHistoryOpen(true)}
                title={t("group.history.title")}
              >
                <span style={{ marginRight: 4 }}>📜</span>{t("group.history")}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={newSession}
                title={t("group.newSession.title")}
              >
                <span style={{ marginRight: 4 }}>＋</span>{t("group.newSession")}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setWizardOpen(true)}
                title={t("group.newGroup.title")}
              >
                <span style={{ marginRight: 4 }}>＋</span>{t("group.newGroup")}
              </Button>
              {memberBots.slice(0, 4).map((b, i) => (
                <div
                  key={b.id}
                  style={{
                    marginLeft: i === 0 ? 0 : -10,
                    border: "2px solid var(--surface-2)",
                    borderRadius: "50%",
                  }}
                >
                  <Avatar emoji={b.emoji} size={32} color={avatarColor(b.name)} />
                </div>
              ))}
              {memberBots.length > 4 && (
                <div
                  style={{
                    marginLeft: -10,
                    width: 32,
                    height: 32,
                    borderRadius: "50%",
                    background: "var(--surface-solid)",
                    border: "2px solid var(--surface-2)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 11,
                    fontWeight: 600,
                    color: "var(--fg-muted)",
                  }}
                >
                  +{memberBots.length - 4}
                </div>
              )}
            </div>
          </div>

          {/* Messages */}
          <div
            style={{
              flex: 1,
              minHeight: 0,
              overflowY: "auto",
              padding: 24,
              display: "flex",
              flexDirection: "column",
              gap: 14,
              // Custom scrollbar already defined globally; this just ensures
              // it shows up once content exceeds the panel height.
              scrollBehavior: "smooth",
            }}
          >
            {messages.length === 0 ? (
              <EmptyState
                emoji="💭"
                title={t("group.empty.title")}
                description={
                  memberBots.length === 0
                    ? t("group.empty.desc_no_bots")
                    : t("group.empty.desc")
                }
              />
            ) : (
              messages.map((m) => {
                const bot = m.botId ? bots.find((b) => b.id === m.botId) : undefined;
                return (
                  <ChatBubble key={m.id} bubble={m} bot={bot} knownBots={memberBots} />
                );
              })
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Composer (pinned to bottom; never scrolls with messages) */}
          <div
            style={{
              padding: 16,
              borderTop: "1px solid var(--border)",
              background: "var(--surface-2)",
              flexShrink: 0,
            }}
          >
            <Composer
              bots={memberBots}
              onSend={send}
              onStop={stop}
              streaming={streaming}
              groupId={groupId}
            />
          </div>
        </section>
        <GroupWizard
          open={wizardOpen}
          onOpenChange={setWizardOpen}
          bots={bots}
          onCreated={(g) => {
            setWizardOpen(false);
            // Force a full remount of the page so old group's messages
            // / active speaker / streaming state don't bleed into the
            // newly created group.
            window.location.href = `/group/${g.id}`;
          }}
        />

        {/* History drawer: past sessions in this group, reopenable. */}
        {historyOpen && (
          <div
            onClick={() => setHistoryOpen(false)}
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(0, 0, 0, 0.35)",
              zIndex: 50,
              display: "flex",
              justifyContent: "flex-end",
            }}
          >
            <div
              onClick={(e) => e.stopPropagation()}
              style={{
                width: 340,
                maxWidth: "90vw",
                height: "100%",
                background: "var(--surface-solid)",
                borderLeft: "1px solid var(--border)",
                display: "flex",
                flexDirection: "column",
                boxShadow: "-8px 0 24px rgba(0,0,0,0.12)",
              }}
            >
              <div
                style={{
                  padding: "16px 20px",
                  borderBottom: "1px solid var(--border)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <div style={{ fontSize: 15, fontWeight: 600 }}>
                  📜 {t("group.history.title")}
                </div>
                <button
                  onClick={() => setHistoryOpen(false)}
                  title={t("common.cancel")}
                  style={{ fontSize: 18, color: "var(--fg-muted)", lineHeight: 1, padding: "0 4px" }}
                >
                  ×
                </button>
              </div>

              <div style={{ padding: 12, borderBottom: "1px solid var(--border)" }}>
                <Button variant="secondary" size="sm" onClick={showAllMessages} style={{ width: "100%" }}>
                  {t("group.history.all")}
                </Button>
              </div>

              <div
                style={{
                  flex: 1,
                  overflowY: "auto",
                  padding: 12,
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                {runs.length === 0 ? (
                  <div style={{ textAlign: "center", color: "var(--fg-subtle)", padding: 40, fontSize: 13 }}>
                    {t("group.history.empty")}
                  </div>
                ) : (
                  runs.map((run) => (
                    <button
                      key={run.id}
                      onClick={() => selectRun(run.id)}
                      style={{
                        textAlign: "left",
                        padding: 12,
                        borderRadius: "var(--radius)",
                        background:
                          activeRunId === run.id
                            ? "rgba(167, 139, 250, 0.12)"
                            : "var(--surface-2)",
                        border:
                          activeRunId === run.id
                            ? "1px solid rgba(167, 139, 250, 0.35)"
                            : "1px solid var(--border)",
                        transition: "all var(--transition)",
                      }}
                    >
                      <div style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.4, marginBottom: 6 }}>
                        {run.user_prompt.length > 60
                          ? `${run.user_prompt.slice(0, 60)}…`
                          : run.user_prompt}
                      </div>
                      <div
                        style={{
                          fontSize: 11,
                          color: "var(--fg-subtle)",
                          display: "flex",
                          justifyContent: "space-between",
                        }}
                      >
                        <span>{new Date(run.started_at).toLocaleString()}</span>
                        <span>{t("group.history.sessionCount", { n: run.message_count })}</span>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function makeId() {
  return Math.random().toString(36).slice(2);
}