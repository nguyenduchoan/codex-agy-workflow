#!/usr/bin/env python3
"""Subscription-based Git handoff orchestrator. No third-party Python dependencies."""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import shutil
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit


class WorkflowError(Exception):
    pass


class MissingDocument(WorkflowError):
    pass


def require(condition, message):
    if not condition:
        raise WorkflowError(message)


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            os.chmod(temporary, 0o600)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def safe_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value), "Invalid run_id")
    return value


@dataclasses.dataclass
class Config:
    repo: str
    remote_url: str
    branch: str = "main"
    test_command: list[str] = dataclasses.field(default_factory=lambda: ["python3", "-m", "unittest", "-v"])
    codex_command: list[str] = dataclasses.field(default_factory=lambda: ["codex"])
    agy_command: list[str] = dataclasses.field(default_factory=lambda: ["agy"])
    codex_home: str | None = None
    web_enabled: bool = False
    web_effort: str = "xhigh"
    agent_timeout: int = 900
    test_timeout: int = 120
    max_iterations: int = 3
    protected_paths: list[str] = dataclasses.field(default_factory=list)

    def __post_init__(self):
        self.repo = str(Path(self.repo).expanduser().resolve())
        require(isinstance(self.remote_url, str) and bool(self.remote_url), "remote_url is required")
        require(not any(c in self.remote_url for c in "\r\n\t"), "Invalid remote URL")
        if self.remote_url.startswith(("https://", "http://")):
            require(urlsplit(self.remote_url).username is None, "Do not embed credentials in remote_url")
        for command in (self.test_command, self.codex_command, self.agy_command):
            require(isinstance(command, list) and command and all(isinstance(v, str) and v and "\0" not in v for v in command), "Commands must be nonempty argv arrays")
        require(self.web_effort in ("medium", "high", "xhigh"), "Unsupported web effort")
        require(type(self.web_enabled) is bool, "web_enabled must be boolean")
        for value in (self.agent_timeout, self.test_timeout, self.max_iterations):
            require(type(value) is int and 1 <= value <= 86400, "Invalid timeout/iteration limit")
        require(self.max_iterations <= 3, "Pilot allows at most three implementation rounds")
        require(isinstance(self.branch, str) and not self.branch.startswith("-"), "Invalid branch")
        for path in self.protected_paths:
            require(isinstance(path, str) and path and not path.startswith("/") and ".." not in PurePosixPath(path).parts and ":" not in path, "Invalid protected path")
        if self.codex_home:
            self.codex_home = str(Path(self.codex_home).expanduser().resolve())

    def fingerprint(self):
        return hashlib.sha256(json.dumps(dataclasses.asdict(self), sort_keys=True).encode()).hexdigest()


class Git:
    def __init__(self, config: Config):
        self.config = config
        self.repo = Path(config.repo)
        self.call("check-ref-format", "--branch", config.branch)
        require(Path(self.call("rev-parse", "--show-toplevel")).resolve() == self.repo, "repo must be the repository root")
        common = Path(self.call("rev-parse", "--git-common-dir"))
        self.store = (common if common.is_absolute() else self.repo / common).resolve() / "agy-workflow"

    def call(self, *args, check=True):
        try:
            result = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, timeout=45)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WorkflowError("Git command could not finish: " + str(error)) from error
        if check:
            require(result.returncode == 0, "Git command failed: " + " ".join(args[:2]))
        return result.stdout.decode("utf-8").strip() if check else result

    @property
    def head(self):
        return self.call("rev-parse", "HEAD")

    def identity(self):
        require(self.call("remote", "get-url", "origin") == self.config.remote_url, "origin URL changed or does not match config")
        require(self.call("remote", "get-url", "--push", "origin") == self.config.remote_url, "origin push URL does not match config")
        require(self.call("branch", "--show-current") == self.config.branch, "Checkout is on the wrong branch")

    def clean(self):
        self.identity()
        require(not self.call("status", "--porcelain", "--untracked-files=all"), "Working tree is dirty; preserved without changes")

    def remote_head(self):
        self.identity()
        branch = self.config.branch
        self.call("fetch", "--no-tags", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
        return self.call("rev-parse", f"refs/remotes/origin/{branch}")

    def ancestor(self, older, newer):
        return self.call("merge-base", "--is-ancestor", older, newer, check=False).returncode == 0

    def changes(self, older, newer):
        output = self.call("diff", "--name-only", "--no-renames", "-z", older, newer, check=False)
        require(output.returncode == 0, "Cannot compare Git revisions")
        return [name.decode("utf-8") for name in output.stdout.split(b"\0") if name]

    def docs_only(self, older, newer, prefix):
        require(self.ancestor(older, newer), "Reviewed version is not an ancestor; history changed")
        require(all(p.startswith(prefix + "/") and p.endswith(".md") for p in self.changes(older, newer)), "Code changed after review; request a fresh review")

    def sync(self, revision):
        self.clean()
        require(self.ancestor(self.head, revision), "Local and remote history diverged or local commits are unpushed")
        self.call("merge", "--ff-only", revision)

    def document(self, revision, path):
        entry = self.call("ls-tree", revision, "--", path)
        if not entry:
            raise MissingDocument("Document has not been pushed: " + path)
        require(entry.startswith("100644 blob "), "Document must be a regular Markdown file")
        size = int(self.call("cat-file", "-s", revision + ":" + path))
        require(size <= 1024 * 1024, "Document exceeds 1 MiB")
        commit = self.call("log", "-1", "--format=%H", revision, "--", path)
        return self.call("show", commit + ":" + path), commit


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON metadata key")
        result[key] = value
    return result


def parse_document(text, *, run_id, iteration, kind, reviewed_sha):
    match = re.search(r"^```json\s*\n(.*?)\n```\s*$", text, re.M | re.S)
    require(match is not None and match.start() < 1024, "Document needs a JSON metadata block at the top")
    try:
        metadata = json.loads(match.group(1), object_pairs_hook=unique_object)
    except (ValueError, TypeError) as error:
        raise WorkflowError("Invalid document metadata") from error
    require(isinstance(metadata, dict), "Document metadata must be an object")
    require(metadata.get("run_id") == run_id, "Wrong run_id")
    require(type(metadata.get("iteration")) is int and metadata["iteration"] == iteration, "Wrong iteration")
    require(metadata.get("kind") == kind, "Wrong document kind")
    require(metadata.get("reviewed_code_sha") == reviewed_sha, "Wrong reviewed_code_sha")
    allowed = {"READY"} if kind == "plan" else {"PASS", "CHANGES_REQUESTED"}
    require(metadata.get("status") in allowed, "Invalid document status")
    headings = list(re.finditer(r"^## Prompt bàn giao cho agy\s*$", text, re.M))
    require(len(headings) == 1, "Document needs exactly one AGY prompt heading")
    prompt = re.split(r"^## ", text[headings[0].end():], maxsplit=1, flags=re.M)[0].strip()
    require(bool(prompt) and len(prompt) <= 100_000, "Missing or oversized handoff prompt")
    return metadata, prompt


@dataclasses.dataclass
class Result:
    returncode: int
    stdout: str
    reason: str = ""


class ProcessRunner:
    """File-backed output avoids pipe deadlocks; every process has a bounded lifetime."""
    deadline = None

    def run(self, argv, *, cwd, input_text, timeout, logbase, stop_file, env=None):
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
        if timeout <= 0 or stop_file.exists():
            return Result(-1, "", "timeout" if timeout <= 0 else "stop requested")
        logbase.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        paths = [Path(str(logbase) + suffix) for suffix in (".stdin", ".stdout", ".stderr")]
        paths[0].write_text(input_text, encoding="utf-8")
        for path in paths:
            path.touch(mode=0o600, exist_ok=True)
            os.chmod(path, 0o600)
        reason = ""
        with paths[0].open("rb") as source, paths[1].open("wb") as out, paths[2].open("wb") as err:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=source, stdout=out, stderr=err, start_new_session=True)
            try:
                end = time.monotonic() + timeout
                while proc.poll() is None:
                    if stop_file.exists():
                        reason = "stop requested"
                    elif time.monotonic() >= end:
                        reason = "timeout"
                    elif paths[1].stat().st_size + paths[2].stat().st_size > 16 * 1024 * 1024:
                        reason = "output limit"
                    if reason:
                        break
                    time.sleep(0.1)
            except BaseException:
                self.terminate(proc)
                raise
            finally:
                if reason or proc.poll() is None:
                    self.terminate(proc)
                else:
                    # A completed command must not leave children from this run alive.
                    self.terminate(proc)
        with paths[1].open("rb") as handle:
            output = handle.read(16 * 1024 * 1024).decode("utf-8", errors="replace")
        return Result(proc.returncode, output, reason)

    @staticmethod
    def terminate(proc):
        # Signal only the process group created for this invocation, including descendants.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def events(text):
    result = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            result.append(item)
    return result


def quota_error(text):
    # Deliberately ignore prose, assistant messages, tool output and generic HTTP 429.
    for event in events(text):
        if event.get("type") not in ("turn.failed", "error"):
            continue
        error = event.get("error", event if event.get("type") == "error" else None)
        if not isinstance(error, dict):
            continue
        if error.get("code") in ("usage_limit_reached", "insufficient_quota") or error.get("codexErrorInfo") == "usageLimitExceeded":
            return True
        # Some CLI versions preserve only the service's canonical quota message.
        # Match its exact leading sentence only inside an error event, never arbitrary prose.
        message = error.get("message")
        if isinstance(message, str) and message.replace("’", "'").startswith("You've hit your usage limit."):
            return True
    return False


class Agents:
    def __init__(self, config, runner):
        self.config, self.runner = config, runner

    def request(self, provider, prompt, logbase, stop_file):
        cfg = self.config
        require(not any(os.environ.get(key) for key in ("OPENAI_API_KEY", "CODEX_API_KEY")), "API key environment detected; subscription-only run refused")
        require(provider == "native" or cfg.web_enabled, "Web bridge has not been enabled and validated")
        env = dict(os.environ)
        if cfg.codex_home:
            env["CODEX_HOME"] = cfg.codex_home
        model = "gpt-6-astra" if provider == "native" else "chatgpt-web/gpt-5.6-sol"
        effort = "xhigh" if provider == "native" else cfg.web_effort
        argv = [*cfg.codex_command, "exec", "--json", "--color", "never", "-m", model,
                "-c", 'model_provider="openai"', "-c", 'forced_login_method="chatgpt"',
                "-c", f'model_reasoning_effort="{effort}"', "-c", 'approval_policy="never"',
                "-c", "sandbox_workspace_write.network_access=true",
                "-s", "workspace-write", "-"]
        return self.runner.run(argv, cwd=cfg.repo, input_text=prompt, timeout=cfg.agent_timeout,
                               logbase=logbase, stop_file=stop_file, env=env)

    def implement(self, prompt, conversation_id, logbase, stop_file):
        argv = [*self.config.agy_command, "--dangerously-skip-permissions", "--disable-slash-commands",
                "--input-format", "stream-json", "--output-format", "stream-json",
                "--print-timeout", f"{self.config.agent_timeout}s"]
        if conversation_id:
            argv.extend(["--conversation", conversation_id])
        data = json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False) + "\n"
        return self.runner.run(argv, cwd=self.config.repo, input_text=data, timeout=self.config.agent_timeout,
                               logbase=logbase, stop_file=stop_file)


class Workflow:
    def __init__(self, config, *, runner=None, agents=None):
        self.config = config
        self.git = Git(config)
        self.store = self.git.store
        self.store.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_path = self.store / "state.json"
        self.stop_file = self.store / "stop"
        self.runner = runner or ProcessRunner()
        self.agents = agents or Agents(config, self.runner)

    @contextlib.contextmanager
    def lock(self):
        with (self.store / "lock").open("a") as handle:
            os.chmod(self.store / "lock", 0o600)
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise WorkflowError("Another workflow owns this repository") from error
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def load(self):
        require(self.state_path.exists(), "Run init first")
        state = json.loads(self.state_path.read_text())
        require(state["config_hash"] == self.config.fingerprint(), "Config changed during the run; restore it before resuming")
        return state

    def save(self, state, phase=None, detail=None):
        if phase:
            state["phase"] = phase
        if detail is not None:
            state["detail"] = detail
        state["updated_at"] = time.time()
        atomic_json(self.state_path, state)
        return state

    def init(self, run_id, goal, review_existing=False):
        safe_id(run_id)
        if self.state_path.exists():
            previous = json.loads(self.state_path.read_text())
            require(previous["phase"] in ("DONE", "CANCELED") and not previous.get("pending"), "Previous run is unfinished")
            require(previous["run_id"] != run_id, "Use a new run_id")
            atomic_json(self.store / previous["run_id"] / "final-state.json", previous)
        self.git.clean()
        self.git.sync(self.git.remote_head())
        self.stop_file.unlink(missing_ok=True)
        state = {"version": 1, "run_id": run_id, "goal": goal, "config_hash": self.config.fingerprint(),
                 "config": dataclasses.asdict(self.config),
                 "phase": "REVIEWING" if review_existing else "PLANNING", "kind": "review" if review_existing else "plan",
                 "iteration": 1 if review_existing else 0, "reviewed_code_sha": self.git.head,
                 "implementations": 0, "pending": None, "consumed": [], "conversation_id": None,
                 "provider": "web" if review_existing else "native", "detail": "Initialized"}
        return self.save(state)

    def prefix(self, state):
        return "workflow-runs/" + safe_id(state["run_id"])

    def docpath(self, state):
        name = "plan.md" if state["kind"] == "plan" else f'review-{state["iteration"]:02d}.md'
        return self.prefix(state) + "/" + name

    def logbase(self, state, operation):
        return self.store / state["run_id"] / f'{state["iteration"]:02d}-{operation}-{uuid.uuid4().hex[:8]}'

    def request_prompt(self, state):
        metadata = {"run_id": state["run_id"], "iteration": state["iteration"], "kind": state["kind"],
                    "reviewed_code_sha": state["reviewed_code_sha"],
                    "status": "READY" if state["kind"] == "plan" else "CHANGES_REQUESTED or PASS"}
        return (f"Làm {state['kind']} cho yêu cầu: {state['goal']}\n"
                f"Repo: {self.config.remote_url}; branch: {self.config.branch}; mã cần đọc: {state['reviewed_code_sha']}.\n"
                f"Đọc mã thật và tự tạo/push duy nhất {self.docpath(state)} lên nhánh trên. Không sửa mã/test, không tạo PR. "
                "Không force-push; nếu nhánh đổi mã thì dừng và báo. Không sử dụng API model trả phí.\n"
                "Đầu tệp cần một khối ```json với metadata sau (status chỉ chọn một giá trị hợp lệ):\n"
                + json.dumps(metadata, ensure_ascii=False) + "\n"
                "Sau đó ghi nhận xét, bằng chứng, tiêu chí kiểm thử và mục '## Prompt bàn giao cho agy'. "
                "Mục đó phải có chỉ dẫn thực thi; nếu PASS ghi 'Không cần sửa'. Yêu cầu AGY giữ nguyên kiểm thử được bảo vệ, "
                "chạy kiểm thử, commit và push mã khi hoàn tất. Chỉ báo đã push khi có bằng chứng Git.\n"
                f"Kết quả test độc lập gần nhất: {json.dumps(state.get('tests'), ensure_ascii=False)}")

    def validate_document(self, state):
        self.git.clean()
        head = self.git.remote_head()
        self.git.docs_only(state["reviewed_code_sha"], head, self.prefix(state))
        text, commit = self.git.document(head, self.docpath(state))
        self.git.docs_only(state["reviewed_code_sha"], commit, self.prefix(state))
        metadata, prompt = parse_document(text, run_id=state["run_id"], iteration=state["iteration"],
                                          kind=state["kind"], reviewed_sha=state["reviewed_code_sha"])
        self.git.sync(head)
        return {"path": self.docpath(state), "commit": commit, "remote_head": head,
                "sha256": hashlib.sha256(text.encode()).hexdigest(), "metadata": metadata, "prompt": prompt}

    def tests(self, state):
        before = self.git.head
        result = self.runner.run(self.config.test_command, cwd=self.config.repo, input_text="",
                                 timeout=self.config.test_timeout, logbase=self.logbase(state, "tests"), stop_file=self.stop_file)
        self.git.clean()
        require(self.git.head == before, "Tests changed the Git revision")
        state["tests"] = {"sha": before, "returncode": result.returncode, "reason": result.reason}
        return result

    def request(self, state):
        self.git.clean()
        self.git.sync(self.git.remote_head())
        self.git.docs_only(state["reviewed_code_sha"], self.git.head, self.prefix(state))
        if state["provider"] == "web" and not self.config.web_enabled:
            return self.save(state, "NEEDS_INPUT", "Web bridge is disabled; no message was sent")
        # Reconcile remote first, including when the previous send finished but the parent crashed.
        try:
            self.validate_document(state)
        except MissingDocument:
            pass
        else:
            return self.save(state, "WAITING_DOCUMENT", "Existing document found; skipped duplicate request")
        state["pending"] = {"action": "request", "provider": state["provider"], "started_at": time.time()}
        self.save(state, "REQUESTING_DOCUMENT")
        result = self.agents.request(state["provider"], self.request_prompt(state), self.logbase(state, "request"), self.stop_file)
        if result.reason:
            return self.save(state, "NEEDS_INPUT", "Request interrupted; reconcile Git before any retry: " + result.reason)
        try:
            self.validate_document(state)
        except MissingDocument:
            pass
        else:
            state["pending"] = None
            return self.save(state, "WAITING_DOCUMENT", "Document verified even if response was interrupted")
        if quota_error(result.stdout):
            state["pending"] = None
            if state["provider"] == "native" and self.config.web_enabled:
                state["provider"] = "web"
                return self.save(state, "PLANNING", "Typed native quota error; next step uses web")
            return self.save(state, "WAITING_QUOTA", "Typed quota error; no usable fallback")
        if result.returncode == 0 and any(e.get("type") == "turn.completed" for e in events(result.stdout)):
            state["pending"] = None
            return self.save(state, "WAITING_DOCUMENT", "Agent completed; still require the document on Git")
        return self.save(state, "NEEDS_INPUT", "Agent did not complete; no automatic resend")

    def receive(self, state):
        try:
            document = self.validate_document(state)
        except MissingDocument as error:
            return self.save(state, "WAITING_DOCUMENT", str(error))
        key = f'{state["kind"]}:{state["iteration"]}:{document["commit"]}'
        require(key not in state["consumed"], "This document was already consumed")
        state["document"] = document
        state["document_key"] = key
        state["pending"] = None
        if document["metadata"]["status"] == "PASS":
            self.save(state, "TESTING_FINAL")
            result = self.tests(state)
            require(result.returncode == 0 and not result.reason, "Review says PASS but independent tests failed")
            latest = self.git.remote_head()
            self.git.docs_only(state["reviewed_code_sha"], latest, self.prefix(state))
            current = self.validate_document(state)
            require(current["sha256"] == document["sha256"], "Review changed while testing")
            state["consumed"].append(key)
            return self.save(state, "DONE", "Git review and independent tests passed")
        require(state["implementations"] < self.config.max_iterations, "Implementation limit reached")
        return self.save(state, "READY_TO_IMPLEMENT", "Verified Git document")

    def implement(self, state):
        current = self.validate_document(state)
        require(current["commit"] == state["document"]["commit"] and current["sha256"] == state["document"]["sha256"], "Document changed before AGY dispatch")
        before = self.git.head
        state["pending"] = {"action": "implement", "before": before, "document_key": state["document_key"]}
        self.save(state, "IMPLEMENTING")
        prompt = (f"Repo hiện tại {self.config.remote_url}, branch {self.config.branch}. Đọc tài liệu {current['path']} "
                  f"ở commit {current['commit']}. Thực hiện trong repo này, không force-push hoặc reset, "
                  f"không sửa các tệp được bảo vệ {self.config.protected_paths}, không sửa tài liệu bàn giao. "
                  f"Chạy {json.dumps(self.config.test_command)}, commit và push mã khi hoàn tất.\n\n" + current["prompt"])
        result = self.agents.implement(prompt, state["conversation_id"], self.logbase(state, "agy"), self.stop_file)
        receipts = [e["result"] for e in events(result.stdout) if e.get("event") == "result" and isinstance(e.get("result"), dict)]
        require(result.returncode == 0 and not result.reason and len(receipts) == 1 and receipts[0].get("status") == "SUCCESS", "AGY result is incomplete; reconcile instead of rerunning")
        conversation = receipts[0].get("conversation_id")
        require(isinstance(conversation, str) and re.fullmatch(r"[A-Za-z0-9_-]+", conversation), "AGY did not return a usable conversation ID")
        if state["conversation_id"]:
            require(conversation == state["conversation_id"], "AGY returned another conversation")
        state["conversation_id"] = conversation
        return self.verify_implementation(state)

    def verify_implementation(self, state):
        require((state.get("pending") or {}).get("action") == "implement", "No implementation to reconcile")
        before = state["pending"]["before"]
        self.git.clean()
        after = self.git.remote_head()
        require(self.git.head == after and self.git.ancestor(before, after), "AGY result must be committed and pushed without rewriting history")
        changes = self.git.changes(before, after)
        require(changes and any(not p.startswith(self.prefix(state) + "/") for p in changes), "No code progress")
        require(not set(changes).intersection(self.config.protected_paths), "AGY changed a protected file")
        require(not any(p.startswith(self.prefix(state) + "/") for p in changes), "AGY changed reviewer documents")
        self.save(state, "TESTING")
        result = self.tests(state)
        require(not result.reason, "Independent tests interrupted: " + result.reason)
        require(self.git.remote_head() == after, "Remote changed during implementation verification")
        state["consumed"].append(state["pending"]["document_key"])
        state["pending"] = None
        state["implementations"] += 1
        state["iteration"] += 1
        state["kind"] = "review"
        state["reviewed_code_sha"] = after
        state["provider"] = "web"
        return self.save(state, "REVIEWING", "AGY code verified; request an independent web review")

    def step(self):
        state = self.load()
        try:
            if self.stop_file.exists():
                return self.save(state, "NEEDS_INPUT" if state.get("pending") else "CANCELED", "Stop requested")
            phase = state["phase"]
            if phase in ("PLANNING", "REVIEWING"):
                return self.request(state)
            if phase == "WAITING_DOCUMENT":
                return self.receive(state)
            if phase == "READY_TO_IMPLEMENT":
                return self.implement(state)
            if phase in ("REQUESTING_DOCUMENT", "IMPLEMENTING", "TESTING", "TESTING_FINAL"):
                return self.save(state, "NEEDS_INPUT", "Previous operation was interrupted; run reconcile")
            return state
        except KeyboardInterrupt:
            self.save(state, "NEEDS_INPUT" if state.get("pending") else "CANCELED", "Interrupted by operator")
            raise
        except (WorkflowError, OSError) as error:
            return self.save(state, "NEEDS_INPUT", str(error))

    def reconcile(self, action):
        state = self.load()
        self.stop_file.unlink(missing_ok=True)
        if action == "document":
            # This operation only reads Git; it never sends another model request.
            self.validate_document(state)
            state["pending"] = None
            return self.save(state, "WAITING_DOCUMENT", "Document found during reconciliation")
        if action == "implementation":
            return self.verify_implementation(state)
        require(action == "retry-request", "Unknown reconciliation action")
        require(not state.get("pending") or state["pending"].get("action") == "request", "Cannot retry an ambiguous implementation")
        self.git.clean()
        self.git.docs_only(state["reviewed_code_sha"], self.git.remote_head(), self.prefix(state))
        try:
            self.validate_document(state)
        except MissingDocument:
            state["pending"] = None
            return self.save(state, "PLANNING" if state["kind"] == "plan" else "REVIEWING", "Operator explicitly authorized retry")
        state["pending"] = None
        return self.save(state, "WAITING_DOCUMENT", "Document already exists; skipped retry")

    def update_config(self):
        require(self.state_path.exists(), "Run init first")
        state = json.loads(self.state_path.read_text())
        require(not state.get("pending"), "Reconcile the outstanding action before updating config")
        before = state["config"]
        after = dataclasses.asdict(self.config)
        allowed = {"web_enabled", "web_effort", "codex_home"}
        require(all(before.get(k) == v for k, v in after.items() if k not in allowed), "Only web settings and codex_home can change within a run")
        state["config"], state["config_hash"] = after, self.config.fingerprint()
        return self.save(state, detail="Config updated; no agent was started")

    def doctor(self):
        self.git.clean()
        commands = {name: shutil.which(argv[0]) for name, argv in
                    (("codex", self.config.codex_command), ("agy", self.config.agy_command), ("test", self.config.test_command))}
        return {"repo_clean": True, "branch": self.config.branch, "commands": commands,
                "web_enabled": self.config.web_enabled, "web_effort": self.config.web_effort,
                "api_key_env_present": any(os.environ.get(k) for k in ("OPENAI_API_KEY", "CODEX_API_KEY")),
                "note": "Read-only check. Live auth, web capability, MCP and push permissions still need validation."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("init")
    start.add_argument("--run-id", required=True)
    start.add_argument("--goal-file", required=True, type=Path)
    start.add_argument("--review-existing", action="store_true")
    for name in ("status", "step", "stop", "prompt", "doctor", "update-config"):
        commands.add_parser(name)
    run = commands.add_parser("run")
    run.add_argument("--max-wait", type=int, default=600)
    run.add_argument("--poll", type=int, default=10)
    repair = commands.add_parser("reconcile")
    repair.add_argument("action", choices=("document", "implementation", "retry-request"))
    args = parser.parse_args(argv)
    try:
        config = Config(**json.loads(args.config.read_text()))
        workflow = Workflow(config)
        if args.command == "doctor":
            print(json.dumps(workflow.doctor(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "stop":
            workflow.stop_file.touch(mode=0o600)
            print("Stop requested; active child will be terminated by its owner")
            return 0
        if args.command == "status":
            print(json.dumps(workflow.load(), ensure_ascii=False, indent=2))
            return 0
        with workflow.lock():
            if args.command == "init":
                state = workflow.init(args.run_id, args.goal_file.read_text(), args.review_existing)
            elif args.command == "prompt":
                print(workflow.request_prompt(workflow.load()))
                return 0
            elif args.command == "reconcile":
                state = workflow.reconcile(args.action)
            elif args.command == "update-config":
                state = workflow.update_config()
            elif args.command == "step":
                state = workflow.step()
            else:
                require(1 <= args.max_wait <= 7200 and 1 <= args.poll <= 60, "Invalid run time bounds")
                end = time.monotonic() + args.max_wait
                workflow.runner.deadline = end
                while True:
                    state = workflow.step()
                    print(json.dumps({"phase": state["phase"], "detail": state.get("detail")}, ensure_ascii=False), flush=True)
                    if state["phase"] in ("DONE", "CANCELED", "NEEDS_INPUT", "WAITING_QUOTA") or time.monotonic() >= end:
                        break
                    if state["phase"] == "WAITING_DOCUMENT":
                        # Cooperative wait: a stop file wakes this loop within 0.2 seconds.
                        until = min(time.monotonic() + args.poll, end)
                        while time.monotonic() < until and not workflow.stop_file.exists():
                            time.sleep(0.2)
            print(json.dumps({"phase": state["phase"], "detail": state.get("detail"), "run_id": state["run_id"]}, ensure_ascii=False))
            return 2 if state["phase"] in ("NEEDS_INPUT", "WAITING_QUOTA") else 0
    except (WorkflowError, ValueError, TypeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
