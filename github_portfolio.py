"""GitHub Portfolio & Codebase Intelligence Integrator.

Performs deep repository inspection (reading file trees, dependency manifests,
database schemas, Docker/CI configurations, and full READMEs) across local workspaces
and remote GitHub repositories to generate factual, concrete project descriptions.
"""

import base64
import json
import os
import re
import subprocess
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv()

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".github_portfolio_cache.json")
CACHE_TTL_SECONDS = 86400  # 24 hours
USER_HOME = os.path.expanduser("~")

# In-progress or incomplete projects to exclude from active resumes
EXCLUDED_REPOSITORIES = {
    "secure-devops-scanner",
    "securedevopsscanner",
}

FEATURED_EXTERNAL_REPOSITORIES = [
    {
        "owner": "GenAI-Scientific-Literature-System",
        "name": "GenAI-Scientific-Literature-System-multi-agent-system",
        "full_name": "GenAI-Scientific-Literature-System/GenAI-Scientific-Literature-System-multi-agent-system",
        "url": "https://github.com/GenAI-Scientific-Literature-System/GenAI-Scientific-Literature-System-multi-agent-system",
        "description": "A Multi-Agent Generative AI System for Scientific Literature Analysis. Selected for IEEE SPICES Conference (Zenodo DOI: 10.5281/zenodo.22676649). Coordinated agent ensemble with graph-based Louvain clustering.",
        "language": "Python",
        "topics": ["multi-agent-systems", "generative-ai", "scientific-literature-analysis", "graph-clustering", "rag", "ieee-spices"]
    }
]

IGNORED_DIRS = {
    "node_modules", ".git", ".venv", "dist", "build", ".next",
    "__pycache__", ".pytest_cache", ".DS_Store", ".idea", ".vscode"
}

MANIFEST_FILES = {
    "package.json", "requirements.txt", "pyproject.toml", "Cargo.toml",
    "docker-compose.yml", "docker-compose.yaml", "Dockerfile",
    "schema.prisma", "Makefile", "setup.py"
}


def is_repo_excluded(repo_name: str) -> bool:
    normalized = re.sub(r"[-_]", "", (repo_name or "").lower().strip())
    return any(normalized == re.sub(r"[-_]", "", ex.lower()) for ex in EXCLUDED_REPOSITORIES)


def get_github_username() -> str:
    """Extract GitHub username from environment or parse from resume.md."""
    env_user = os.getenv("GITHUB_USERNAME")
    if env_user:
        return env_user.strip()

    resume_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.md")
    if os.path.exists(resume_path):
        try:
            with open(resume_path, "r", encoding="utf-8") as f:
                content = f.read()
                match = re.search(r"github\.com/([a-zA-Z0-9_-]+)", content, re.I)
                if match:
                    return match.group(1).strip()
        except Exception:
            pass

    return "madhavofficial"


def inspect_local_repository(repo_path: str) -> dict:
    """Read full local directory structure, manifests, and architecture files."""
    file_tree = []
    manifests = {}
    readme_text = ""

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        rel_root = os.path.relpath(root, repo_path)

        for f in files:
            if f.startswith("."):
                continue
            rel_file = os.path.normpath(os.path.join(rel_root, f)) if rel_root != "." else f
            file_tree.append(rel_file)

            if f.lower() == "readme.md" and not readme_text:
                try:
                    with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fp:
                        readme_text = fp.read()[:3000]
                except Exception:
                    pass

            if f in MANIFEST_FILES or f.endswith(".prisma") or f.endswith(".sql") or f.endswith(".proto"):
                if len(manifests) < 8:  # Cap at 8 key architecture/manifest files
                    try:
                        with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fp:
                            manifests[rel_file] = fp.read()[:1200]
                    except Exception:
                        pass

    return {
        "file_tree": file_tree[:40],
        "manifests": manifests,
        "readme_text": readme_text,
    }


def inspect_remote_repository(username: str, repo_name: str, headers: dict) -> dict:
    """Fetch remote git tree and manifest files via GitHub REST API."""
    file_tree = []
    manifests = {}
    readme_text = ""

    try:
        # Fetch README
        readme_url = f"https://api.github.com/repos/{username}/{repo_name}/readme"
        res = requests.get(readme_url, headers=headers, timeout=6)
        if res.status_code == 200:
            res_data = res.json()
            if isinstance(res_data, dict):
                raw = res_data.get("content", "")
                if raw:
                    readme_text = base64.b64decode(raw).decode("utf-8", errors="ignore")[:3000]

        # Fetch git tree
        tree_url = f"https://api.github.com/repos/{username}/{repo_name}/git/trees/HEAD?recursive=1"
        res = requests.get(tree_url, headers=headers, timeout=8)
        if res.status_code == 200:
            res_tree = res.json()
            tree_data = res_tree.get("tree", []) if isinstance(res_tree, dict) else []
            for item in tree_data:
                path = item.get("path", "")
                if not any(ign in path.split("/") for ign in IGNORED_DIRS):
                    file_tree.append(path)
                    basename = os.path.basename(path)
                    if (basename in MANIFEST_FILES or path.endswith(".prisma") or path.endswith(".sql")) and len(manifests) < 6:
                        # Fetch file content
                        f_url = f"https://api.github.com/repos/{username}/{repo_name}/contents/{path}"
                        f_res = requests.get(f_url, headers=headers, timeout=6)
                        if f_res.status_code == 200:
                            f_data = f_res.json()
                            if isinstance(f_data, dict):
                                f_raw = f_data.get("content", "")
                                if f_raw:
                                    manifests[path] = base64.b64decode(f_raw).decode("utf-8", errors="ignore")[:1200]
    except Exception as e:
        print(f"Warning: Failed remote inspection for '{repo_name}': {e}", file=sys.stderr)

    return {
        "file_tree": file_tree[:40],
        "manifests": manifests,
        "readme_text": readme_text,
    }


def fetch_github_portfolio(username: str = None, force_refresh: bool = False) -> list[dict]:
    """Fetch all repositories with deep codebase inspection (local first, then remote)."""
    username = username or get_github_username()

    if not force_refresh and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                cached_time = cached_data.get("timestamp", 0)
                if time.time() - cached_time < CACHE_TTL_SECONDS and cached_data.get("username") == username:
                    repos = cached_data.get("repositories", [])
                    return [r for r in repos if not is_repo_excluded(r.get("name", ""))]
        except Exception as e:
            print(f"Warning: Failed to read GitHub cache: {e}", file=sys.stderr)

    headers = {
        "User-Agent": "JobHunter-Codebase-Inspector/2.0",
        "Accept": "application/vnd.github.v3+json",
    }
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    # 1. Try gh CLI first for full collaborator & org repo access
    repos = []
    try:
        gh_res = subprocess.run(
            ["gh", "api", "user/repos?affiliation=owner,collaborator,organization_member", "--paginate"],
            capture_output=True,
            text=True,
            timeout=12
        )
        if gh_res.returncode == 0:
            repos = json.loads(gh_res.stdout)
    except Exception:
        pass

    # 2. Fallback to standard GitHub REST API
    if not repos:
        try:
            url = f"https://api.github.com/users/{username}/repos?per_page=100&sort=updated"
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                repos = res.json()
        except Exception as e:
            print(f"Warning: GitHub API error: {e}", file=sys.stderr)

    # 3. Always ensure featured research & organization repositories are included
    for feat in FEATURED_EXTERNAL_REPOSITORIES:
        if not any(r.get("name") == feat["name"] for r in repos):
            repos.append({
                "name": feat["name"],
                "full_name": feat["full_name"],
                "owner": {"login": feat["owner"]},
                "html_url": feat["url"],
                "description": feat["description"],
                "language": feat["language"],
                "topics": feat["topics"],
                "fork": False
            })

    portfolio = []
    seen_names = set()

    for r in repos:
        if r.get("fork", False):
            continue
        name = r.get("name", "")
        full_name = r.get("full_name", f"{username}/{name}")
        owner_login = r.get("owner", {}).get("login", username)
        
        if is_repo_excluded(name) or name in seen_names:
            continue
        seen_names.add(name)

        description = r.get("description") or ""
        language = r.get("language") or ""
        topics = r.get("topics") or []
        html_url = r.get("html_url") or f"https://github.com/{full_name}"

        # Check if repo exists locally on disk
        local_path = os.path.join(USER_HOME, name)
        if os.path.isdir(local_path):
            inspection = inspect_local_repository(local_path)
            source_type = "local_filesystem"
        else:
            inspection = inspect_remote_repository(owner_login, name, headers)
            source_type = "remote_github"

        project_item = {
            "name": name,
            "full_name": full_name,
            "owner": owner_login,
            "url": html_url,
            "language": language,
            "description": description,
            "topics": topics,
            "source_type": source_type,
            "file_tree": inspection.get("file_tree", []),
            "manifests": inspection.get("manifests", {}),
            "readme_content": inspection.get("readme_text", ""),
        }
        portfolio.append(project_item)

    # Save to cache
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "username": username,
                "timestamp": time.time(),
                "repositories": portfolio
            }, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save GitHub portfolio cache: {e}", file=sys.stderr)

    return portfolio


def format_github_portfolio_for_prompt(portfolio: list[dict]) -> str:
    """Format deep codebase inspection data into a compact, high-density context for LLM project selection and bullet generation."""
    if not portfolio:
        return "No external GitHub repositories found."

    sections = []
    for p in portfolio:
        p_name = p.get("name", "")
        p_url = p.get("url", "")
        p_desc = p.get("description", "")
        lang = p.get("language") or "N/A"
        file_tree = p.get("file_tree") or []
        manifests = p.get("manifests") or {}
        readme = p.get("readme_content") or ""

        deps = []
        for m_path, m_content in manifests.items():
            if "package.json" in m_path:
                try:
                    data = json.loads(m_content)
                    for k in list(data.get("dependencies", {}).keys())[:6]:
                        if k not in deps:
                            deps.append(k)
                except Exception:
                    pass
            elif "requirements.txt" in m_path:
                for line in m_content.splitlines():
                    cleaned = line.split("==")[0].split(">=")[0].strip()
                    if cleaned and not cleaned.startswith("#") and cleaned not in deps:
                        deps.append(cleaned)

        block = f"### Project: {p_name}\n"
        block += f"- **Repository**: {p_url}\n"
        block += f"- **Primary Language**: {lang}"
        if deps:
            block += f" | Key Dependencies: {', '.join(deps[:8])}"
        block += "\n"
        if p_desc:
            block += f"- **Overview**: {p_desc}\n"
        if file_tree:
            core_files = [f for f in file_tree if any(k in f.lower() for k in ["src", "backend", "prisma", "api", "app", "server", "docker", "infra"])]
            files_str = ", ".join(core_files[:6]) if core_files else ", ".join(file_tree[:6])
            block += f"- **Codebase Structure & Key Files**: {files_str}\n"
        if readme:
            clean_readme = [l.strip() for l in readme.splitlines() if l.strip() and not l.startswith("#") and not l.startswith("!") and not l.startswith("```")]
            block += f"- **Architecture & Verified Capabilities**: {' '.join(clean_readme[:4])[:300]}\n"

        sections.append(block)

    return "\n".join(sections)
