#!/usr/bin/env python3
"""Publish dropped HTML reports into cangjie-report-site and push GitHub Pages.

The script scans only top-level *.html files in the drop directory. Each file is
copied to reports/auto/<slug>/index.html, reports/auto/index.html is regenerated,
and changes under reports/auto are committed and pushed to origin/main.
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
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parents[1]
DROP_DIR = Path(os.environ.get("REPORT_SITE_DROP_DIR", "/Users/cjdebug/workspace/PR/report-site-drop"))
AUTO_DIR = SITE_ROOT / "reports" / "auto"
STATE_FILE = AUTO_DIR / "publish-state.json"
LOCK_FILE = AUTO_DIR / ".publish.lock"


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=SITE_ROOT, check=check, text=True, capture_output=True)


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
    for src in html_files:
        digest = sha256_file(src)
        existing = reports.get(src.name)
        if existing and existing.get("sha256") == digest:
            continue
        slug = slug_for(src, digest)
        dst_dir = AUTO_DIR / slug
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst_dir / "index.html")
        reports[src.name] = {
            "source_name": src.name,
            "slug": slug,
            "title": extract_title(src),
            "sha256": digest,
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
    run(["git", "commit", "-m", f"docs: auto publish reports {msg_date}"])
    run(["git", "push", "origin", "main"])
    print("Published reports/auto to origin/main.")


def main() -> int:
    AUTO_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another publish run is active; exiting.")
            return 0
        try:
            changed = publish_reports()
            if changed:
                if os.environ.get("REPORT_SITE_SKIP_GIT") == "1":
                    print("REPORT_SITE_SKIP_GIT=1; generated files without committing or pushing.")
                else:
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
