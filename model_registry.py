#!/usr/bin/env python3
"""
Model Registry - User-driven model submission to GitHub repo.

Allows AI to discover new models and users to submit them
to the agent-bootstrap repository for future lookups.
"""

import os
import json
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict


@dataclass
class ModelEntry:
    """Model entry for registry"""
    provider: str
    model_name: str
    context_window: int = 0
    max_output_tokens: int = 0
    supports_function_calling: bool = False
    supports_vision: bool = False
    supports_tools: bool = False
    pricing_input_per_1m: Optional[float] = None
    pricing_output_per_1m: Optional[float] = None
    submitted_by: str = "user"
    submitted_at: float = 0.0

    def __post_init__(self):
        if self.submitted_at == 0.0:
            self.submitted_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    def to_yaml_entry(self) -> str:
        """Generate YAML entry for providers.yaml"""
        lines = [
            f"    - name: \"{self.model_name}\"",
            f"      context: {self.context_window}" if self.context_window > 0 else None,
            f"      max_output: {self.max_output_tokens}" if self.max_output_tokens > 0 else None,
            f"      vision: {str(self.supports_vision).lower()}" if self.supports_vision else None,
            f"      function_calling: {str(self.supports_function_calling).lower()}" if self.supports_function_calling else None,
            f"      tools: {str(self.supports_tools).lower()}" if self.supports_tools else None,
        ]
        return "\n".join(l for l in lines if l is not None)


class ModelRegistry:
    """
    User-driven model registry.

    Users can submit new models they discover.
    Models are staged locally, then can be pushed to GitHub repo.
    """

    def __init__(self, repo_path: str = None, staging_file: str = None):
        """
        Args:
            repo_path: Path to agent-bootstrap repo (for git operations)
            staging_file: Local staging file for pending submissions
        """
        if repo_path is None:
            repo_path = os.path.join(os.path.expanduser("~"), ".agent-bootstrap")
        if staging_file is None:
            staging_file = os.path.join(repo_path, "pending_models.json")

        self.repo_path = repo_path
        self.staging_file = staging_file
        self._ensure_dirs()

    def _ensure_dirs(self):
        os.makedirs(os.path.dirname(self.staging_file), exist_ok=True)

    def submit_model(self, entry: ModelEntry) -> Dict[str, Any]:
        """
        Submit a new model for registry.

        Returns:
            {"status": "staged", "entry": dict, "message": str}
        """
        pending = self._load_pending()
        pending.append(entry)
        self._save_pending(pending)

        return {
            "status": "staged",
            "entry": entry.to_dict(),
            "message": f"Model {entry.model_name} staged for submission",
            "pending_count": len(pending),
        }

    def list_pending(self) -> List[Dict[str, Any]]:
        """List all pending model submissions"""
        return [e.to_dict() for e in self._load_pending()]

    def push_to_github(self,
                          github_token: str = None,
                          repo: str = "your-username/agent-bootstrap",
                          branch: str = "main") -> Dict[str, Any]:
        """
        Push pending models to GitHub repo via API.

        Args:
            github_token: GitHub personal access token (or set GITHUB_TOKEN env)
            repo: Target repo in format "owner/repo"
            branch: Target branch

        Returns:
            {"status": "success", "pushed": int, "pr_url": str} or error
        """
        token = github_token or os.environ.get("GITHUB_TOKEN")
        if not token:
            return {
                "status": "error",
                "message": "GITHUB_TOKEN not set and no token provided",
            }

        pending = self._load_pending()
        if not pending:
            return {"status": "ok", "message": "No pending models to push"}

        # Build YAML content for providers.yaml update
        yaml_updates = self._build_yaml_updates(pending)

        # Use GitHub API to create/update files
        import base64
        import urllib.request
        import urllib.error

        results = []
        for provider, models_yaml in yaml_updates.items():
            path = f"providers/providers.yaml"
            url = f"https://api.github.com/repos/{repo}/contents/{path}"

            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            }

            # Get current file to get its SHA
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req) as resp:
                    current = json.loads(resp.read())
                    current_sha = current["sha"]
                    current_content = base64.b64decode(current["content"]).decode("utf-8")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    current_sha = None
                    current_content = ""
                else:
                    return {"status": "error", "message": f"GitHub API error: {e}"}

            # Append new model entries
            new_content = current_content.rstrip() + "\n" + models_yaml

            # Create a branch for this update
            import subprocess
            branch_name = f"add-models-{int(time.time())}"

            # Use gh CLI if available (simpler)
            try:
                gh_cmd = [
                    "gh", "api", "-X", "PUT",
                    f"/repos/{repo}/contents/{path}",
                    "-F", f"message=Add new models: {', '.join(e.model_name for e in pending)}",
                    "-F", f"content={new_content}",
                    "-F", f"branch={branch_name}",
                ]
                if current_sha:
                    gh_cmd.extend(["-F", f"sha={current_sha}"])
                result = subprocess.run(
                    gh_cmd,
                    env={**os.environ, "GITHUB_TOKEN": token},
                    capture_output=True,
                    text=True,
                )

                if result.returncode == 0:
                    results.append({"model": provider, "status": "ok"})
                else:
                    results.append({"model": provider, "status": "error", "detail": result.stderr})
            except FileNotFoundError:
                # gh not installed, try raw API
                update_data = {
                    "message": f"Add new models: {', '.join(e.model_name for e in pending)}",
                    "content": base64.b64encode(new_content.encode()).decode(),
                    "branch": branch_name,
                }
                if current_sha:
                    update_data["sha"] = current_sha

                req = urllib.request.Request(
                    url,
                    data=json.dumps(update_data).encode(),
                    headers={**headers, "Content-Type": "application/json"},
                    method="PUT",
                )
                try:
                    with urllib.request.urlopen(req) as resp:
                        result = json.loads(resp.read())
                        results.append({"model": provider, "status": "ok", "commit": result.get("commit", {}).get("sha")})
                except urllib.error.HTTPError as e:
                    results.append({"model": provider, "status": "error", "detail": str(e)})

        # Clear pending on success
        if all(r["status"] == "ok" for r in results):
            self._save_pending([])

        return {
            "status": "success" if all(r["status"] == "ok" for r in results) else "partial",
            "results": results,
            "pushed": len([r for r in results if r["status"] == "ok"]),
            "pending_remaining": len(self._load_pending()),
        }

    def _build_yaml_updates(self, entries: List[ModelEntry]) -> Dict[str, str]:
        """Build YAML update strings grouped by provider"""
        by_provider: Dict[str, List[ModelEntry]] = {}
        for e in entries:
            if e.provider not in by_provider:
                by_provider[e.provider] = []
            by_provider[e.provider].append(e)

        result = {}
        for provider, models in by_provider.items():
            lines = [f"\n# Auto-submitted models:"]
            for m in models:
                lines.append(m.to_yaml_entry())
            result[provider] = "\n".join(lines)

        return result

    def _load_pending(self) -> List[ModelEntry]:
        try:
            with open(self.staging_file, "r") as f:
                data = json.load(f)
                return [ModelEntry(**d) for d in data]
        except FileNotFoundError:
            return []
        except Exception:
            return []

    def _save_pending(self, entries: List[ModelEntry]):
        with open(self.staging_file, "w") as f:
            json.dump([e.to_dict() for e in entries], f, indent=2, ensure_ascii=False)


# ── Convenience functions ──

_global_registry: Optional[ModelRegistry] = None


def get_registry() -> ModelRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = ModelRegistry()
    return _global_registry


def submit_model(provider: str,
                  model_name: str,
                  context_window: int = 0,
                  max_output_tokens: int = 0,
                  supports_function_calling: bool = False,
                  supports_vision: bool = False,
                  supports_tools: bool = False,
                  pricing_input_per_1m: float = None,
                  pricing_output_per_1m: float = None) -> Dict[str, Any]:
    """
    Simple model submission API for AI/scripts.

    Example:
        result = submit_model(
            provider="openai",
            model_name="gpt-4-turbo",
            context_window=128000,
            supports_vision=True,
        )
    """
    entry = ModelEntry(
        provider=provider,
        model_name=model_name,
        context_window=context_window,
        max_output_tokens=max_output_tokens,
        supports_function_calling=supports_function_calling,
        supports_vision=supports_vision,
        supports_tools=supports_tools,
        pricing_input_per_1m=pricing_input_per_1m,
        pricing_output_per_1m=pricing_output_per_1m,
    )
    return get_registry().submit_model(entry)


def push_to_github(github_token: str = None) -> Dict[str, Any]:
    """Push staged models to GitHub repo"""
    return get_registry().push_to_github(github_token=github_token)


if __name__ == "__main__":
    # Demo
    result = submit_model(
        provider="openai",
        model_name="gpt-4-new-model",
        context_window=128000,
        supports_vision=True,
    )
    print(json.dumps(result, indent=2))
