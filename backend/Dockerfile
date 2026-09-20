FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 写一份 pip.conf 镜像源（覆盖 ENV + 用户级 + 系统级，避免
# `pip install --user` 之类绕过 ENV 时仍走官方 PyPI）。同时也把
# trusted-host 一起放进配置，否则有些镜像站返回的 TLS 证书路径
# 在容器里不被默认信任。
RUN mkdir -p /etc/pip && \
    printf '%s\n' \
        '[global]' \
        'index-url = https://mirrors.aliyun.com/pypi/simple/' \
        'extra-index-url = https://pypi.tuna.tsinghua.edu.cn/simple' \
        'trusted-host = mirrors.aliyun.com pypi.tuna.tsinghua.edu.cn' \
        > /etc/pip/pip.conf

WORKDIR /app

# 使用阿里云 Debian 镜像源加速 apt 下载（默认 archive.ubuntu.com
# 在国内极慢）；同时为新的 trixie sources.list.d 形式与旧
# /etc/apt/sources.list 形式都做替换。
# LibreOffice（headless）用于把 Word / PPT / Excel 转成 PDF，让 KB 里
# 非 PDF 的源文件也能在浏览器里预览 —— MinerU 只回解析产物（md/json），
# 不提供它内部转换出的 PDF，所以这一步只能自己做。
# `fonts-noto-cjk` 是必需的：不装的话中文会整篇渲染成方框（tofu）。
RUN sed -i \
        -e 's|deb.debian.org|mirrors.aliyun.com|g' \
        -e 's|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i \
        -e 's|deb.debian.org|mirrors.aliyun.com|g' \
        -e 's|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list 2>/dev/null || true; \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    libreoffice-writer libreoffice-impress libreoffice-calc \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Install deps in a separate layer for better caching. PyPI mirrors
# (configured in /etc/pip/pip.conf above) are fast enough; we don't
# vendor wheels because they're build artefacts and would only bloat
# the git history without changing the resulting image.
RUN pip install --upgrade pip setuptools wheel && \
    pip install -e .

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

EXPOSE 8000

CMD ["/app/entrypoint.sh"]