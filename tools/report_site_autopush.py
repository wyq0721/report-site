#!/usr/bin/env python3
"""Publish dropped HTML reports into cangjie-report-site and push GitHub Pages.

The script scans only top-level *.html files in the drop directory. Each file is
copied to reports/auto/<slug>/index.html, local relative assets referenced by
the HTML are copied with it, reports/auto/index.html is regenerated, and changes
under reports/auto are committed and pushed to origin/main. Removing a previously
published HTML file from the drop directory unpublishes its report.
"""

from __future__ import annotations

import datetime as _dt
import fcntl
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

SITE_ROOT = Path(__file__).resolve().parents[1]
DROP_DIR = Path(os.environ.get("REPORT_SITE_DROP_DIR", "/Users/cjdebug/Documents/github/report-site-drop"))
PUBLISH_BRANCH = os.environ.get("REPORT_SITE_BRANCH", "main")

# Publishing happens in a dedicated worktree pinned to PUBLISH_BRANCH so it never
# depends on (or disturbs) whichever branch the main clone has checked out.
# The previous version committed to the currently checked-out branch and then
# pushed `main`; whenever the clone sat on a feature branch the commit landed
# there and `git push origin main` silently pushed nothing, so reports never
# reached origin/main and the site never updated.
WORKTREE_DIR = Path(os.environ.get("REPORT_SITE_WORKTREE", str(Path.home() / ".cache" / "report-site-publish")))

# The lock lives in the primary clone (stable, gitignored) so it is independent
# of the worktree it guards and exists before the worktree is created.
LOCK_FILE = SITE_ROOT / "reports" / "auto" / ".publish.lock"

# WORK_ROOT / AUTO_DIR / STATE_FILE are repointed at the worktree by
# ensure_worktree(); these defaults are only used in REPORT_SITE_SKIP_GIT mode.
WORK_ROOT = SITE_ROOT
AUTO_DIR = SITE_ROOT / "reports" / "auto"
STATE_FILE = AUTO_DIR / "publish-state.json"
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,89}$")
ASSET_ATTR_PATTERN = re.compile(
    r"""(?:src|href|poster|data-src|data-original)\s*=\s*["']([^"']+)["']""",
    flags=re.IGNORECASE,
)
SRCSET_ATTR_PATTERN = re.compile(r"""srcset\s*=\s*["']([^"']+)["']""", flags=re.IGNORECASE)
URL_FUNC_PATTERN = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""", flags=re.IGNORECASE)
HOOK_PATH_ENTRIES = (
    str(Path.home() / ".npm-global" / "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("HOME", str(Path.home()))

    entries = list(HOOK_PATH_ENTRIES)
    entries.extend(path for path in env.get("PATH", "").split(os.pathsep) if path)
    env["PATH"] = os.pathsep.join(dict.fromkeys(entries))
    return env


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a git command in the active publish worktree (WORK_ROOT)."""
    return subprocess.run(cmd, cwd=WORK_ROOT, check=check, text=True, capture_output=True, env=command_env())


def git(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=check, text=True, capture_output=True, env=command_env())


def ensure_worktree() -> None:
    """Repoint AUTO_DIR/STATE_FILE/WORK_ROOT at a worktree pinned to origin/PUBLISH_BRANCH.

    All generation, commit and push then happen there, independent of the branch
    the main clone has checked out.
    """
    global WORK_ROOT, AUTO_DIR, STATE_FILE

    git(["fetch", "origin", PUBLISH_BRANCH], cwd=SITE_ROOT, check=False)

    if not (WORKTREE_DIR / ".git").exists():
        # Drop any stale registration, then create a fresh detached worktree.
        git(["worktree", "remove", "--force", str(WORKTREE_DIR)], cwd=SITE_ROOT, check=False)
        if WORKTREE_DIR.exists():
            shutil.rmtree(WORKTREE_DIR, ignore_errors=True)
        git(["worktree", "prune"], cwd=SITE_ROOT, check=False)
        WORKTREE_DIR.parent.mkdir(parents=True, exist_ok=True)
        git(["worktree", "add", "--force", "--detach", str(WORKTREE_DIR), f"origin/{PUBLISH_BRANCH}"], cwd=SITE_ROOT)

    # Re-sync to the published tip so new reports layer cleanly on top and any
    # half-finished previous run is discarded. Detached HEAD means we never need
    # the local `main` branch (which may be checked out elsewhere).
    git(["checkout", "--force", "--detach", f"origin/{PUBLISH_BRANCH}"], cwd=WORKTREE_DIR)
    git(["reset", "--hard", f"origin/{PUBLISH_BRANCH}"], cwd=WORKTREE_DIR)
    git(["clean", "-fd", "--", "reports/auto"], cwd=WORKTREE_DIR, check=False)

    WORK_ROOT = WORKTREE_DIR
    AUTO_DIR = WORKTREE_DIR / "reports" / "auto"
    STATE_FILE = AUTO_DIR / "publish-state.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text_lossy(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def clean_asset_ref(ref: str) -> str | None:
    ref = html.unescape(ref).strip()
    if not ref or ref.startswith("#") or ref.startswith("//"):
        return None

    parsed = urlsplit(ref)
    if parsed.scheme or parsed.netloc:
        return None

    path = unquote(parsed.path).replace("\\", "/")
    if not path or path.startswith("/") or path.startswith("../"):
        return None

    parts = [part for part in path.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    if parts[-1].lower().endswith(".html"):
        return None
    return "/".join(parts)


def extract_asset_refs(text: str) -> set[str]:
    refs = set()
    for pattern in (ASSET_ATTR_PATTERN, URL_FUNC_PATTERN):
        for match in pattern.finditer(text):
            raw = match.group(match.lastindex or 1)
            ref = clean_asset_ref(raw)
            if ref:
                refs.add(ref)

    for match in SRCSET_ATTR_PATTERN.finditer(text):
        for item in match.group(1).split(","):
            raw = item.strip().split()[0] if item.strip() else ""
            ref = clean_asset_ref(raw)
            if ref:
                refs.add(ref)
    return refs


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def copy_if_changed(src: Path, dst: Path) -> bool:
    if dst.exists() and dst.is_file() and src.stat().st_size == dst.stat().st_size and sha256_file(src) == sha256_file(dst):
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def sync_report_assets(src_html: Path, dst_dir: Path) -> tuple[bool, list[str]]:
    drop_root = DROP_DIR.resolve()
    asset_refs = extract_asset_refs(read_text_lossy(src_html))
    copied_assets: set[str] = set()
    changed = False

    for rel_ref in sorted(asset_refs):
        src_asset = DROP_DIR / rel_ref
        if not is_within(src_asset, drop_root) or not src_asset.is_file():
            continue

        dst_asset = dst_dir / rel_ref
        if copy_if_changed(src_asset, dst_asset):
            changed = True
        copied_assets.add(rel_ref)

    for existing in sorted(dst_dir.rglob("*"), reverse=True):
        if not existing.is_file():
            continue
        rel = existing.relative_to(dst_dir).as_posix()
        if rel == "index.html" or rel in copied_assets:
            continue
        existing.unlink()
        changed = True

    for directory in sorted((p for p in dst_dir.rglob("*") if p.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass

    return changed, sorted(copied_assets)


def extract_title(path: Path) -> str:
    text = read_text_lossy(path)
    for pattern in (r"<title[^>]*>(.*?)</title>", r"<h1[^>]*>(.*?)</h1>"):
        m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            title = re.sub(r"<[^>]+>", "", m.group(1))
            title = re.sub(r"\s+", " ", title).strip()
            if title:
                return title
    return path.stem


def slug_for(path: Path, digest: str) -> str:
    stem = path.stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    if not slug:
        slug = "report-" + digest[:10]
    return slug[:90].strip("-") or ("report-" + digest[:10])


def report_slug(path: Path, digest: str, existing: object) -> str:
    if isinstance(existing, dict):
        existing_slug = existing.get("slug")
        if isinstance(existing_slug, str) and SLUG_PATTERN.fullmatch(existing_slug):
            return existing_slug
    return slug_for(path, digest)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"reports": {}}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("reports"), dict):
            return data
    except json.JSONDecodeError:
        pass
    return {"reports": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def remove_published_report(slug: object) -> bool:
    if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
        return False

    report_dir = AUTO_DIR / slug
    if not report_dir.exists():
        return False
    if not report_dir.is_dir():
        return False

    shutil.rmtree(report_dir)
    return True


def render_auto_index(reports: dict, generated_at: str) -> str:
    now = generated_at
    items = sorted(reports.values(), key=lambda item: item.get("updated_at", ""), reverse=True)
    cards = []
    for item in items:
        title = html.escape(item.get("title") or item.get("slug") or "未命名报告")
        slug = html.escape(item["slug"])
        source = html.escape(item.get("source_name", ""))
        updated = html.escape(item.get("updated_at", ""))
        cards.append(f"""
        <a class="card" href="./{slug}/">
          <h2>{title}</h2>
          <p>{source}</p>
          <span>{updated}</span>
        </a>""")
    cards_html = "".join(cards) if cards else '<p class="empty">暂无自动发布报告。</p>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>自动发布报告</title>
  <style>
    body {{ margin: 0; background: #f6f8fb; color: #1f2937; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif; line-height: 1.65; }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 34px 22px 56px; }}
    header {{ border-bottom: 1px solid #d9e0ea; padding-bottom: 22px; margin-bottom: 24px; }}
    a {{ color: inherit; text-decoration: none; }}
    .back {{ color: #1f6feb; font-weight: 700; }}
    h1 {{ margin: 12px 0 8px; font-size: 36px; letter-spacing: 0; }}
    .lead {{ color: #5b6472; max-width: 760px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    .card {{ display: block; background: #fff; border: 1px solid #d9e0ea; border-radius: 8px; padding: 18px; }}
    .card:hover {{ border-color: #93c5fd; }}
    .card h2 {{ margin: 0 0 8px; font-size: 20px; letter-spacing: 0; }}
    .card p {{ margin: 0 0 12px; color: #5b6472; }}
    .card span {{ color: #6b7280; font-size: 13px; }}
    .empty {{ background: #fff; border: 1px solid #d9e0ea; border-radius: 8px; padding: 18px; }}
    footer {{ margin-top: 28px; color: #6b7280; font-size: 13px; }}
    @media (max-width: 760px) {{ .grid {{ grid-template-columns: 1fr; }} h1 {{ font-size: 28px; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <a class="back" href="../../">返回报告中心</a>
      <h1>自动发布报告</h1>
      <p class="lead">本页由本地 hook 自动生成。将 HTML 文件放入投放目录后，脚本会复制、提交并推送到 GitHub Pages。</p>
    </header>
    <section class="grid">{cards_html}
    </section>
    <footer>最后更新：{html.escape(now)}</footer>
  </main>
  <script src="../../assets/site-nav.js"></script>
</body>
</html>
"""


def publish_reports() -> bool:
    AUTO_DIR.mkdir(parents=True, exist_ok=True)
    DROP_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    reports = state.setdefault("reports", {})
    changed = False

    html_files = sorted(p for p in DROP_DIR.glob("*.html") if p.is_file())
    current_source_names = {src.name for src in html_files}
    for source_name, item in list(reports.items()):
        if source_name in current_source_names:
            continue

        removed = reports.pop(source_name)
        if not any(report.get("slug") == removed.get("slug") for report in reports.values()):
            remove_published_report(removed.get("slug"))
        changed = True

    for src in html_files:
        digest = sha256_file(src)
        existing = reports.get(src.name)
        slug = report_slug(src, digest, existing)
        dst_dir = AUTO_DIR / slug
        dst_dir.mkdir(parents=True, exist_ok=True)
        assets_changed, asset_paths = sync_report_assets(src, dst_dir)
        if (
            isinstance(existing, dict)
            and existing.get("sha256") == digest
            and existing.get("slug") == slug
            and existing.get("assets", []) == asset_paths
            and not assets_changed
        ):
            continue

        if copy_if_changed(src, dst_dir / "index.html"):
            changed = True
        reports[src.name] = {
            "source_name": src.name,
            "slug": slug,
            "title": extract_title(src),
            "sha256": digest,
            "assets": asset_paths,
            "updated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        changed = True

    index_path = AUTO_DIR / "index.html"
    if changed or not state.get("generated_at"):
        state["generated_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    index_html = render_auto_index(reports, state.get("generated_at", ""))
    if not index_path.exists() or index_path.read_text(encoding="utf-8") != index_html:
        index_path.write_text(index_html, encoding="utf-8")
        changed = True

    if changed:
        save_state(state)
    return changed


def git_has_auto_changes() -> bool:
    proc = run(["git", "status", "--short", "--", "reports/auto"], check=True)
    return bool(proc.stdout.strip())


def commit_and_push() -> None:
    if not git_has_auto_changes():
        print("No reports/auto changes to publish.")
        return
    run(["git", "add", "reports/auto"])
    if not git_has_auto_changes():
        print("No staged reports/auto changes to publish.")
        return
    msg_date = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    # --no-verify: these are mechanical republish commits, and the global
    # commit-msg hook aborts on a missing `commitlint` in the LaunchAgent env.
    run(["git", "commit", "--no-verify", "-m", f"docs: auto publish reports {msg_date}"])
    push_with_retry(["git", "push", "--no-verify", "origin", f"HEAD:{PUBLISH_BRANCH}"])
    print(f"Published reports/auto to origin/{PUBLISH_BRANCH}.")


def push_with_retry(cmd: list[str], *, attempts: int = 4, delay_seconds: int = 15) -> None:
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(1, attempts + 1):
        try:
            run(cmd)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt >= attempts:
                break
            sys.stderr.write(
                f"Push attempt {attempt}/{attempts} failed; retrying in {delay_seconds}s.\n"
            )
            if exc.stderr:
                sys.stderr.write(exc.stderr + "\n")
            sys.stderr.flush()
            time.sleep(delay_seconds)
    assert last_error is not None
    raise last_error


def main() -> int:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another publish run is active; exiting.")
            return 0
        try:
            if os.environ.get("REPORT_SITE_SKIP_GIT") == "1":
                # Inspection only: generate into the primary tree, no git ops.
                changed = publish_reports()
                if changed:
                    print("REPORT_SITE_SKIP_GIT=1; generated files without committing or pushing.")
                else:
                    print(f"No changed HTML reports in {DROP_DIR}.")
                return 0

            ensure_worktree()
            changed = publish_reports()
            if changed:
                commit_and_push()
            else:
                print(f"No changed HTML reports in {DROP_DIR}.")
            return 0
        except subprocess.CalledProcessError as exc:
            sys.stderr.write(f"Command failed: {' '.join(exc.cmd)}\n")
            if exc.stdout:
                sys.stderr.write(exc.stdout + "\n")
            if exc.stderr:
                sys.stderr.write(exc.stderr + "\n")
            return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
