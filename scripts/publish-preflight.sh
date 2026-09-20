#!/usr/bin/env bash
# ============================================================
# publish-preflight.sh — publish 分支 push 前检查
#
# 用途：botgroup 项目的 publish 分支专门用于推 GitHub，main 是
# 业务分支。push 前跑这一脚本，命中红线立即拒绝。
#
# 集成方式（可选）：
#   chmod +x scripts/publish-preflight.sh
#   手动：./scripts/publish-preflight.sh
#   或 git hook：cp scripts/publish-preflight.sh .git/hooks/pre-push
#
# ============================================================
set -euo pipefail

# 颜色
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

cd "$(git rev-parse --show-toplevel)"

# 仅当在 publish 分支上跑
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT_BRANCH" != "publish" ]]; then
    echo -e "${YELLOW}⚠️  当前分支是 '$CURRENT_BRANCH'，不是 publish${NC}"
    echo "   此脚本建议在 publish 分支上跑，但你可能有意为之。"
    echo "   继续 y / 退出 n？"
    read -r -p "   (y/N): " ans
    if [[ ! "$ans" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

ERRORS=0
WARNINGS=0

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; ERRORS=$((ERRORS+1)); }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; WARNINGS=$((WARNINGS+1)); }
section() { echo; echo -e "${BLUE}── $1 ──${NC}"; }

# ─── 1. 验证 .gitignore 已 ignore 敏感路径 ─────────────────
section "1. .gitignore 验证"

for path in ".env" ".env.local" "data/" "postgres-data/"; do
    if git check-ignore -q "$path" 2>/dev/null; then
        ok "$path 被 .gitignore 忽略"
    else
        fail "$path 没被 .gitignore 忽略！必须立刻加进去"
    fi
done

# ─── 2. 验证敏感文件没被 git 跟踪 ──────────────────────────
section "2. 已跟踪文件黑名单"

for path in ".env" ".env.local" ".env.production" ".env.development" "data/"; do
    if git ls-files | grep -qxF "$path" 2>/dev/null; then
        fail "$path 被 git 跟踪了！必须 git rm --cached"
    else
        ok "$path 未被 git 跟踪"
    fi
done

# 兜底：递归扫描 data/ 和 .env.* 任何已跟踪文件（排除 .example 模板）
if git ls-files | grep -E '^(\.env|data/|postgres-data/)' | grep -v '\.example$' >/dev/null 2>&1; then
    fail "发现 .env/data/ 下被跟踪的文件（.example 除外）："
    git ls-files | grep -E '^(\.env|data/|postgres-data/)' | grep -v '\.example$' | head -10 | sed 's/^/    /'
else
    ok "data/ 和 .env* 下没有任何已跟踪文件（.example 模板除外）"
fi

# ─── 3. 已跟踪文件 grep 真实 IP / key ──────────────────────
section "3. 已跟踪文件敏感信息扫描"

TRACKED=$(git ls-files)

# 真实内网 IP 模式（粗略，可调）
IP_PATTERN='10\.[0-9]+\.[0-9]+\.[0-9]+|192\.168\.[0-9]+\.[0-9]+|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+'
# 智谱 GLM key
ZHIPU_PATTERN='[a-f0-9]{32}\.[A-Za-z0-9]{8,}'
# OpenAI / NewAPI key
OPENAI_PATTERN='sk-[A-Za-z0-9_-]{20,}'
# 邮箱
EMAIL_PATTERN='[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

SCAN_HITS=0
for file in $TRACKED; do
    [[ -f "$file" ]] || continue
    # 排除 .env.example / 模板文件
    case "$file" in
        *.example|*.tmpl|*.template) continue ;;
    esac
    # 内网 IP
    if grep -qE "$IP_PATTERN" "$file" 2>/dev/null; then
        # 排除 placeholder (<your-host> 或 127.0.0.1 / localhost)
        if grep -E "$IP_PATTERN" "$file" | grep -vE '<your-host>|127\.0\.0\.1|localhost|0\.0\.0\.0|::1' >/dev/null; then
            fail "发现内网 IP in $file:"
            grep -nE "$IP_PATTERN" "$file" | head -3 | sed 's/^/    /'
            SCAN_HITS=$((SCAN_HITS+1))
        fi
    fi
    # OpenAI / NewAPI key
    if grep -qE "$OPENAI_PATTERN" "$file" 2>/dev/null; then
        if ! grep -qE "sk-your-key-here|sk-placeholder" "$file"; then
            fail "发现疑似 OpenAI / NewAPI key in $file:"
            grep -nE "$OPENAI_PATTERN" "$file" | head -3 | sed 's/^/    /'
            SCAN_HITS=$((SCAN_HITS+1))
        fi
    fi
    # 智谱 key
    if grep -qE "$ZHIPU_PATTERN" "$file" 2>/dev/null; then
        if ! grep -qE "your-zhipu-key|placeholder" "$file"; then
            fail "发现疑似智谱 GLM key in $file:"
            grep -nE "$ZHIPU_PATTERN" "$file" | head -3 | sed 's/^/    /'
            SCAN_HITS=$((SCAN_HITS+1))
        fi
    fi
done
if [[ $SCAN_HITS -eq 0 ]]; then
    ok "已跟踪文件无敏感信息"
fi

# ─── 4. .env.example 应是占位符 ─────────────────────────────
section "4. .env.example 完整性"

if [[ ! -f .env.example ]]; then
    fail ".env.example 不存在"
else
    ok ".env.example 存在"
    # 占位符检查
    if grep -qE 'your-newapi\.example\.com|sk-your-key-here|change-me' .env.example; then
        ok "占位符规范"
    else
        warn ".env.example 缺占位符，新用户可能直接 copy"
    fi
fi

# ─── 5. 必填开源文件存在 ────────────────────────────────────
section "5. 开源标准文件"

for f in LICENSE CONTRIBUTING.md SECURITY.md README.md INTRO.md; do
    if [[ -f "$f" ]]; then
        ok "$f 存在"
    else
        fail "$f 缺失！GitHub 用户第一眼会看"
    fi
done

# ─── 6. CI 配置存在 ─────────────────────────────────────────
section "6. CI 配置"

if [[ -f .github/workflows/ci.yml ]]; then
    ok ".github/workflows/ci.yml 存在"
else
    warn "无 CI 配置 — PR 没法自动验证"
fi

# ─── 7. PR / Issue 模板 ──────────────────────────────────────
section "7. GitHub 社区模板"

if [[ -d .github/ISSUE_TEMPLATE ]]; then
    ok ".github/ISSUE_TEMPLATE/ 存在"
else
    warn "无 issue 模板 — 新用户不知怎么提"
fi

if [[ -f .github/PULL_REQUEST_TEMPLATE.md ]]; then
    ok ".github/PULL_REQUEST_TEMPLATE.md 存在"
else
    warn "无 PR 模板"
fi

# ─── 8. Docker / Compose 完整性 ────────────────────────────
section "8. 部署文件"

if [[ -f docker-compose.yml ]] || [[ -f compose.yaml ]]; then
    ok "docker-compose.yml 存在"
else
    fail "无 docker-compose.yml — 用户不知道怎么起"
fi

if [[ -f .dockerignore ]]; then
    ok ".dockerignore 存在"
else
    warn "无 .dockerignore — .env / data/ 可能进 build context"
fi

# ─── 9. 分支健康度 ──────────────────────────────────────────
section "9. 分支 / 远程"

if git remote -v | grep -q .; then
    echo "  已配远程："
    git remote -v | sed 's/^/    /'
else
    warn "没配远程 — git push 会失败"
fi

# 推送目标不是 main 而是 publish 分支？
if git remote -v | grep -E 'github.*\.git\s' | head -1 >/dev/null 2>&1; then
    REMOTE_URL=$(git remote -v | grep -E 'github.*\.git\s' | head -1 | awk '{print $2}')
    echo "  GitHub remote: $REMOTE_URL"
fi

# ─── 总结 ────────────────────────────────────────────────
echo
echo "─────────────────────────────────────────────"
echo -e "  ${GREEN}✓ 通过：$((9 - ERRORS - WARNINGS))${NC} | ${YELLOW}⚠ 警告：$WARNINGS${NC} | ${RED}✗ 错误：$ERRORS${NC}"
echo "─────────────────────────────────────────────"

if [[ $ERRORS -gt 0 ]]; then
    echo
    echo -e "${RED}❌ 有 $ERRORS 项错误，push 应被阻止${NC}"
    echo "   修完后重新跑: ./scripts/publish-preflight.sh"
    exit 1
fi

if [[ $WARNINGS -gt 0 ]]; then
    echo
    echo -e "${YELLOW}⚠️  $WARNINGS 项警告，建议修但可继续 push${NC}"
fi

echo
echo -e "${GREEN}✅ preflight 通过，可以 push 到 GitHub${NC}"
exit 0