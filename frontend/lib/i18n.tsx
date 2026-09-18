"use client";

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

/**
 * Minimal in-house i18n. Two locales: zh-CN (default) and en-US.
 * - Stored in localStorage so the choice persists across reloads.
 * - Server-rendered HTML stays in zh-CN; on hydration we swap to the saved
 *   locale, so the brief flash is acceptable for an internal dashboard.
 *
 * Why not i18next/react-intl? The app is small and labels are short; a 30-line
 * dictionary + t() is enough and ships ~0 KB extra to the bundle.
 */
export type Locale = "zh-CN" | "en-US";

type Dict = Record<string, string>;

const zh: Dict = {
  "app.name": "BotGroup",
  "app.tagline": "multi-bot chat",
  "nav.groups": "群组",
  "nav.bots": "机器人",
  "nav.models": "模型",
  "nav.skills": "技能中心",
  "nav.adminUsers": "用户管理",
  "nav.adminAudit": "审计日志",
  "sidebar.collapse": "折叠侧栏",
  "sidebar.expand": "展开侧栏",
  "sidebar.user": "Local User",
  "sidebar.userRole": "self-hosted",
  "sidebar.logout": "Sign out",
  "groups.title": "群组",
  "groups.subtitle_empty": "创建一个群组开始第一次多机器人讨论",
  "groups.subtitle_count_one": "共 {n} 个群组 · {m} 位机器人",
  "groups.empty.title": "还没有群组",
  "groups.empty.desc_no_bots": "先在「机器人管理」创建几位机器人，再来这里建群开始讨论",
  "groups.empty.desc": "建一个群组，把机器人拉进来一起讨论吧",
  "groups.empty.cta": "创建第一个群组",
  "groups.new": "新建群组",
  "groups.fullTeam": "🏢 一键全员群",
  "groups.fullTeam.creating": "⏳ 创建中…",
  "groups.fullTeam.hint": "一键补齐 11 个角色模板机器人，并建一个把所有人都拉进去的群",
  "groups.fullTeam.toast.noBots": "还没有机器人",
  "groups.fullTeam.toast.noBotsDesc": "先去「机器人管理」用 🏢 一键创建团队，或手动建几个",
  "groups.fullTeam.toast.success": "全员群已创建",
  "groups.fullTeam.toast.successDesc": "新增机器人 {c} 位 · 当前群成员 {n} 位",
  "group.back": "← 返回群组列表",
  "group.members": "群成员",
  "group.membersCount": "{n} 位成员 · 第 {r} 轮",
  "group.addBot": "添加机器人",
  "group.addBotPlaceholder": "选择机器人…",
  "group.remove": "移除",
  "group.noMembers": "还没有成员",
  "group.mode.auto": "Auto",
  "group.mode.manual": "Manual",
  "group.mode.round_robin": "Round Robin",
  "group.rounds": "最多 {n} 轮",
  "group.header.discussing": "● {n} 位机器人正在讨论…",
  "group.header.idle": "{n} 位成员 · 随时输入消息开始讨论",
  "group.header.noTask": "还没有任务，点「新会话」开始",
  "group.empty.title": "开始第一次讨论",
  "group.empty.desc_no_bots": "先把机器人拉进群，然后发个消息试试",
  "group.empty.desc": "输入消息后，机器人会按模式发言；用 @机器人名 触发指定机器人",
  "group.reset": "重新开始",
  "group.reset.title": "清空当前群组的聊天记录，保留群成员重新开始讨论",
  "group.reset.busy": "请等待当前讨论结束后再清空",
  "group.reset.done": "已清空，可以重新开始",
  "group.reset.fail": "清空失败",
  "group.history": "历史",
  "group.history.title": "历史会话",
  "group.history.all": "全部消息",
  "group.history.empty": "暂无历史会话",
  "group.history.sessionCount": "{n} 条消息",
  "group.newSession": "新会话",
  "group.newSession.title": "开一个新会话，历史记录会保留",
  "group.newSession.busy": "请等待当前讨论结束后再开新会话",
  "group.newGroup": "新建群组",
  "group.newGroup.title": "另建一个新群，不影响当前群",
  "common.loading": "加载中…",
  "common.delete": "删除",
  "common.cancel": "取消",
  "common.confirm": "确认",
  "common.save": "保存",
  "common.close": "关闭",
  "common.toast.deleted": "已删除",
  "common.toast.deletedFail": "删除失败",
  "common.toast.loadFail": "加载失败",
  "common.toast.createFail": "创建失败",
  "common.toast.addFail": "添加失败",
  "common.toast.removeFail": "移除失败",
  "common.error": "错误",
  "common.error.unknown": "未知错误",
  "chat.placeholder": "说点什么… (@机器人名 触发指定机器人，Shift+Enter 换行)",
  "chat.stop": "停止",
  "chat.send": "发送",
  "chat.streaming": "正在输入…",
  "chat.uploading": "上传中…",
  "chat.upload.error": "上传失败",
  "lang.zh": "中文",
  "lang.en": "English",
  "lang.label": "语言",
  "login.title": "登 录",
  "login.hint": "使用 BotGroup,配置你的机器人团队,让多个 AI 一起开会",
  "login.oauth.github": "使用 GitHub 继续",
  "login.oauth.linuxdo": "使用 LinuxDO 继续",
  "login.oauth.disabled": "该登录方式暂未启用,请使用邮箱或用户名登录",
  "login.or": "或",
  "login.username": "邮箱或用户名",
  "login.password": "密码",
  "login.submit": "使用 邮箱或用户名 登录",
  "login.submitting": "登录中…",
  "login.termsHint": "我已阅读并同意",
  "login.terms": "《服务条款》",
  "login.privacy": "《隐私政策》",
  "login.bootstrapHint":
    "默认账号 admin / admin,请尽快在 .env 中通过 AUTH_BOOTSTRAP_PASSWORD 修改",
  "login.toast.welcome": "登录成功",
  "login.toast.welcomeDesc": "欢迎回来,{name}",
  "login.toast.fail": "登录失败",
};

const en: Dict = {
  "app.name": "BotGroup",
  "app.tagline": "multi-bot chat",
  "nav.groups": "Groups",
  "nav.bots": "Bots",
  "nav.models": "Models",
  "nav.skills": "Skills",
  "nav.adminUsers": "Users",
  "nav.adminAudit": "Audit Log",
  "sidebar.collapse": "Collapse sidebar",
  "sidebar.expand": "Expand sidebar",
  "sidebar.user": "Local User",
  "sidebar.userRole": "self-hosted",
  "groups.title": "Groups",
  "groups.subtitle_empty": "Create a group to start your first multi-bot discussion",
  "groups.subtitle_count_one": "{n} group · {m} bot",
  "groups.empty.title": "No groups yet",
  "groups.empty.desc_no_bots": "Head to Bots to create a few bots first, then come back here",
  "groups.empty.desc": "Create a group and pull your bots in to start the discussion",
  "groups.empty.cta": "Create your first group",
  "groups.new": "New group",
  "groups.fullTeam": "🏢 Full-team group",
  "groups.fullTeam.creating": "⏳ Creating…",
  "groups.fullTeam.hint": "One-click: top up 11 role-template bots and create a group with all of them",
  "groups.fullTeam.toast.noBots": "No bots yet",
  "groups.fullTeam.toast.noBotsDesc": "Go to Bots and use 🏢 Create team, or add a few manually",
  "groups.fullTeam.toast.success": "Full-team group created",
  "groups.fullTeam.toast.successDesc": "{c} bots created · {n} members in the group",
  "group.back": "← Back to groups",
  "group.members": "Members",
  "group.membersCount": "{n} members · round {r}",
  "group.addBot": "Add bot",
  "group.addBotPlaceholder": "Pick a bot…",
  "group.remove": "Remove",
  "group.noMembers": "No members yet",
  "group.mode.auto": "Auto",
  "group.mode.manual": "Manual",
  "group.mode.round_robin": "Round Robin",
  "group.rounds": "Up to {n} rounds",
  "group.header.discussing": "● {n} bots are discussing…",
  "group.header.idle": "{n} members · type to start",
  "group.header.noTask": "No task yet — hit \"New Chat\" to start",
  "group.empty.title": "Start your first discussion",
  "group.empty.desc_no_bots": "Add some bots to the group, then send a message",
  "group.empty.desc": "Bots will reply in the chosen mode; @botname triggers a specific one",
  "group.reset": "Reset",
  "group.reset.title": "Clear this group's history and start a fresh discussion",
  "group.reset.busy": "Wait for the current discussion to finish",
  "group.reset.done": "Cleared — ready for a fresh start",
  "group.reset.fail": "Failed to clear",
  "group.history": "History",
  "group.history.title": "History",
  "group.history.all": "All messages",
  "group.history.empty": "No history yet",
  "group.history.sessionCount": "{n} messages",
  "group.newSession": "New chat",
  "group.newSession.title": "Start a new session; history is preserved",
  "group.newSession.busy": "Wait for the current discussion to finish",
  "group.newGroup": "New group",
  "group.newGroup.title": "Open a new group without affecting this one",
  "common.loading": "Loading…",
  "common.delete": "Delete",
  "common.cancel": "Cancel",
  "common.confirm": "Confirm",
  "common.save": "Save",
  "common.close": "Close",
  "common.toast.deleted": "Deleted",
  "common.toast.deletedFail": "Delete failed",
  "common.toast.loadFail": "Failed to load",
  "common.toast.createFail": "Create failed",
  "common.toast.addFail": "Add failed",
  "common.toast.removeFail": "Remove failed",
  "common.error": "Error",
  "common.error.unknown": "Unknown error",
  "chat.placeholder": "Say something… (@botname to trigger, Shift+Enter for newline)",
  "chat.stop": "Stop",
  "chat.send": "Send",
  "chat.streaming": "typing…",
  "chat.uploading": "Uploading…",
  "chat.upload.error": "Upload failed",
  "lang.zh": "中文",
  "lang.en": "English",
  "lang.label": "Language",
  "login.title": "Sign in",
  "login.hint":
    "Sign in to configure your bot team and let multiple AIs meet together",
  "login.oauth.github": "Continue with GitHub",
  "login.oauth.linuxdo": "Continue with LinuxDO",
  "login.oauth.disabled":
    "This provider is not enabled. Please sign in with email/username.",
  "login.or": "or",
  "login.username": "Email or username",
  "login.password": "Password",
  "login.submit": "Sign in with email or username",
  "login.submitting": "Signing in…",
  "login.termsHint": "I agree to the",
  "login.terms": "Terms of Service",
  "login.privacy": "Privacy Policy",
  "login.bootstrapHint":
    "Default credentials are admin / admin — change AUTH_BOOTSTRAP_PASSWORD in .env",
  "login.toast.welcome": "Signed in",
  "login.toast.welcomeDesc": "Welcome back, {name}",
  "login.toast.fail": "Sign-in failed",
};

const DICTS: Record<Locale, Dict> = { "zh-CN": zh, "en-US": en };

const STORAGE_KEY = "botgroup.locale";

type I18nCtx = {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
};

const Ctx = createContext<I18nCtx | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("zh-CN");
  // Hydrate the saved locale after mount to avoid SSR hydration mismatch.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY) as Locale | null;
      if (saved === "zh-CN" || saved === "en-US") {
        setLocaleState(saved);
      }
    } catch {
      /* localStorage unavailable — keep default */
    }
  }, []);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
  }, []);

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => {
      const dict = DICTS[locale];
      let s = dict[key] ?? DICTS["zh-CN"][key] ?? key;
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          s = s.split(`{${k}}`).join(String(v));
        }
      }
      return s;
    },
    [locale],
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useI18n must be used inside <I18nProvider>");
  return v;
}