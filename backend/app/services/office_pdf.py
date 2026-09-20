"""Office → PDF 转换（LibreOffice headless）。

KB 里非 PDF 的源文件（Word / PPT / Excel）没法在浏览器里直接预览。
MinerU 虽然内部会把 Office 转成版式化文档，但它只回解析产物
（`full.md` / `layout.json`），**不提供那份 PDF**，所以预览用的 PDF 得自己转。

两条入口：

  - `convert_to_pdf(src, out)`：核心转换，转一次写到指定路径。
    上传接口用它做**入库前转换** —— Office 文件先转成 PDF 再落库，之后整条
    链路（MinerU 解析、chunk 的 page/bbox、浏览器预览）只认 PDF。
  - `ensure_pdf(src, token)`：懒转换 + 落盘缓存的兜底路径，给**存量**数据用
    —— 之前已经以 .docx 存进 KB 的文档，点开预览时按需补一份，缓存名是
    `kb-preview-{token}-{源文件 mtime}.pdf`（mtime 参与 key，源文件换了会重转）。

调用方拿到的是一个**落在 upload_dir 里的文件路径**。之所以不返回 bytes：
PDF 可能几十 MB，让 API 层用 `FileResponse` 从磁盘直接发出去，既省内存又能
走 sendfile。

注意：
  - LibreOffice 首次启动要建用户 profile，必须显式指定
    `-env:UserInstallation`，否则以 root 运行时会在 HOME 上失败。
  - 转换走 `asyncio.create_subprocess_exec`（子进程 + await），不阻塞事件
    循环；单次可能几秒到几十秒，所以有超时上限。
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 转换超时。LibreOffice 遇到畸形文件会挂住，必须有上限。
_CONVERT_TIMEOUT_SECONDS = 180

# 这些格式浏览器不能原生渲染，需要先转 PDF。
CONVERTIBLE_EXTS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}


def needs_pdf_rendition(filename: str) -> bool:
    """该文件是否需要在预览前转成 PDF。"""
    return Path(filename or "").suffix.lower() in CONVERTIBLE_EXTS


def _cache_path(src: Path, token: str) -> Path:
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    # 带上 mtime：源文件被覆盖后 key 变化，会自动重转。
    return upload_dir / f"kb-preview-{token}-{int(src.stat().st_mtime)}.pdf"


async def convert_to_pdf(src: Path, out: Path) -> Path:
    """把 `src` 转成 PDF 写到 `out`，返回 `out`。

    抛 `RuntimeError` 表示失败（LibreOffice 缺失 / 超时 / 产出为空）。调用方
    应该把它转成明确的错误，而不是静默跳过 —— 「转不了」和「转出来是空的」
    对用户是两回事。
    """
    if not src.exists():
        raise RuntimeError(f"源文件不存在：{src.name}")

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("服务端未安装 LibreOffice，无法把该文件转成 PDF")

    out.parent.mkdir(parents=True, exist_ok=True)
    # 输出目录放在 out 的同级（同一文件系统），这样最后归位是一次原子 rename，
    # 而不是「先拷到 /tmp 再搬回来」——跨设备搬运既慢又非原子。
    work_dir = Path(tempfile.mkdtemp(prefix=".kb-convert-", dir=out.parent))
    # 单独的用户 profile 目录，避免 root 下 HOME 不可写导致 soffice 直接退出。
    profile_dir = work_dir / "profile"
    try:
        cmd = [
            soffice,
            "--headless",
            "--norestore",
            "--nolockcheck",
            f"-env:UserInstallation=file://{profile_dir}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(work_dir),
            str(src),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _out, err = await asyncio.wait_for(
                proc.communicate(), timeout=_CONVERT_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(
                f"转换成 PDF 超时（>{_CONVERT_TIMEOUT_SECONDS}s）"
            ) from None
        if proc.returncode != 0:
            detail = (err or b"").decode("utf-8", "replace").strip()[:300]
            raise RuntimeError(f"转换成 PDF 失败：{detail or 'soffice 非零退出'}")

        produced = next(iter(sorted(work_dir.glob("*.pdf"))), None)
        if not produced or produced.stat().st_size == 0:
            raise RuntimeError("转换成 PDF 失败：未生成有效的 PDF 文件")

        produced.replace(out)
        logger.info(
            "converted %s -> %s (%s bytes)", src.name, out.name, out.stat().st_size
        )
        return out
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def ensure_pdf(src: Path, token: str) -> Path:
    """确保 `src` 有一份 PDF 渲染，返回缓存文件路径。

    给**存量**文档用：新上传的 Office 文件在入库前就已经转成 PDF 了（见
    `api.kb.upload_kb_document`），这条路径兜的是历史数据 —— 之前已经以
    .docx 存进 KB 的文档，以及聊天里指向它们的引用，点开预览时按需补一份。

    `token` 是调用方给的稳定标识（这里用 attachment id），用来隔离不同
    源文件的缓存。
    """
    if not src.exists():
        raise RuntimeError(f"源文件不存在：{src.name}")

    cache = _cache_path(src, token)
    if cache.exists() and cache.stat().st_size > 0:
        return cache
    return await convert_to_pdf(src, cache)


def drop_cache(src: Path, token: str) -> None:
    """删除派生缓存。源文件被删/重新上传时调用，避免残留占盘。"""
    try:
        if not src.exists():
            # 源文件已经没了，mtime 取不到，扫一下同 token 的所有缓存。
            for p in Path(settings.upload_dir).glob(f"kb-preview-{token}-*.pdf"):
                p.unlink(missing_ok=True)
            return
        _cache_path(src, token).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        logger.warning("failed to drop pdf preview cache for token=%s", token)
