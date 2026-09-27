"""Behavior tests for the subscription workflow, using only local Git repositories."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

MODULE = Path(__file__).resolve().parents[1] / "workflow.py"
spec = importlib.util.spec_from_file_location("workflow", MODULE)
workflow = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = workflow
assert spec.loader is not None
spec.loader.exec_module(workflow)


def git(path: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=path, text=True, capture_output=True)
    if check and result.returncode:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


class LocalRepos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(self.remote)], check=True, capture_output=True)
        self.repo = self.root / "repo"
        subprocess.run(["git", "clone", str(self.remote), str(self.repo)], check=True, capture_output=True)
        self.configure_git(self.repo)
        (self.repo / "README.md").write_text("seed\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "seed")
        git(self.repo, "push", "-u", "origin", "main")
        self.agent_repo = self.root / "agent"
        subprocess.run(["git", "clone", str(self.remote), str(self.agent_repo)], check=True, capture_output=True)
        self.configure_git(self.agent_repo)
        self.config = workflow.Config(
            repo=str(self.repo), remote_url=str(self.remote), branch="main",
            test_command=["python3", "-c", "pass"], codex_command=["fake-codex"],
            agy_command=["fake-agy"], web_enabled=True, agent_timeout=5, test_timeout=5,
        )
        self.wf = workflow.Workflow(self.config)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def configure_git(path):
        git(path, "config", "user.name", "Workflow Test")
        git(path, "config", "user.email", "workflow-test@example.invalid")

    def commit_and_push(self, path, rel, content, message):
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        git(path, "add", rel)
        git(path, "commit", "-m", message)
        git(path, "push", "origin", "main")
        return git(path, "rev-parse", "HEAD")

    def make_document(self, run_id, iteration, kind, reviewed_sha, status, prompt="Do the work"):
        metadata = {"run_id": run_id, "iteration": iteration, "kind": kind,
                    "reviewed_code_sha": reviewed_sha, "status": status}
        return "```json\n" + json.dumps(metadata) + "\n```\n\n## Evidence\nLocal Git evidence.\n\n## Prompt bàn giao cho agy\n" + prompt + "\n"

    def push_document(self, run_id, iteration, kind, reviewed_sha, status, prompt="Do the work"):
        name = "plan.md" if kind == "plan" else f"review-{iteration:02d}.md"
        path = f"workflow-runs/{run_id}/{name}"
        return self.commit_and_push(self.agent_repo, path,
                                    self.make_document(run_id, iteration, kind, reviewed_sha, status, prompt),
                                    f"add {kind}")


class DocumentMetadataTests(unittest.TestCase):
    def parse(self, metadata):
        text = "```json\n" + metadata + "\n```\n\n## Prompt bàn giao cho agy\nProceed\n"
        return workflow.parse_document(text, run_id="run1", iteration=1,
                                       kind="plan", reviewed_sha="a" * 40)

    def test_valid_metadata_and_prompt_are_returned(self):
        meta, prompt = self.parse(json.dumps({"run_id": "run1", "iteration": 1, "kind": "plan",
                                              "reviewed_code_sha": "a" * 40, "status": "READY"}))
        self.assertEqual(meta["status"], "READY")
        self.assertEqual(prompt, "Proceed")

    def test_duplicate_metadata_key_is_rejected(self):
        with self.assertRaises(workflow.WorkflowError):
            self.parse('{"run_id":"run1","run_id":"run1","iteration":1,"kind":"plan",'
                       '"reviewed_code_sha":"' + "a" * 40 + '","status":"READY"}')

    def test_boolean_is_not_accepted_as_iteration_integer(self):
        with self.assertRaisesRegex(workflow.WorkflowError, "iteration"):
            self.parse('{"run_id":"run1","iteration":true,"kind":"plan",'
                       '"reviewed_code_sha":"' + "a" * 40 + '","status":"READY"}')


class GitWorkflowTests(LocalRepos):
    def test_iteration_limit_blocks_another_implementation(self):
        state = self.wf.init("roundlimit", "goal", review_existing=True)
        state["implementations"] = 3
        self.push_document("roundlimit", 1, "review", state["reviewed_code_sha"], "CHANGES_REQUESTED")
        self.wf.save(state, "WAITING_DOCUMENT")
        result = self.wf.step()
        self.assertEqual(result["phase"], "NEEDS_INPUT")
        self.assertIn("limit reached", result["detail"])

    def test_protected_file_change_blocks_implementation_result(self):
        self.config.protected_paths = ["README.md"]
        self.wf = workflow.Workflow(self.config)
        state = self.wf.init("protected", "goal")
        state["pending"] = {"action": "implement", "before": state["reviewed_code_sha"], "document_key": "example"}
        self.commit_and_push(self.repo, "README.md", "changed\n", "agent changed protected file")
        with self.assertRaisesRegex(workflow.WorkflowError, "protected file"):
            self.wf.verify_implementation(state)

    def test_update_config_keeps_run_but_does_not_send(self):
        self.wf.init("configupdate", "goal")
        self.config.web_effort = "high"
        with self.assertRaisesRegex(workflow.WorkflowError, "Config changed"):
            self.wf.load()
        result = self.wf.update_config()
        self.assertEqual(result["config"]["web_effort"], "high")
        self.assertEqual(self.wf.load()["phase"], "PLANNING")

    def test_pass_is_not_accepted_when_independent_tests_fail(self):
        self.config.test_command = ["python3", "-c", "raise SystemExit(1)"]
        self.wf = workflow.Workflow(self.config)
        state = self.wf.init("falsepass", "review", review_existing=True)
        self.push_document("falsepass", 1, "review", state["reviewed_code_sha"], "PASS")
        self.wf.save(state, "WAITING_DOCUMENT")
        result = self.wf.step()
        self.assertEqual(result["phase"], "NEEDS_INPUT")
        self.assertIn("independent tests failed", result["detail"])

    def test_interrupted_implementation_is_not_repeated(self):
        state = self.wf.init("interrupted", "goal")
        state["pending"] = {"action": "implement", "before": state["reviewed_code_sha"]}
        self.wf.save(state, "IMPLEMENTING")
        spy = SpyAgents()
        self.wf.agents = spy
        result = self.wf.step()
        self.assertEqual(result["phase"], "NEEDS_INPUT")
        self.assertEqual(spy.implement_calls, 0)
        self.assertEqual(result["pending"]["action"], "implement")

    def test_reconcile_finds_document_without_resending_request(self):
        state = self.wf.init("recover", "goal")
        state["pending"] = {"action": "request", "provider": "native"}
        self.wf.save(state, "REQUESTING_DOCUMENT")
        self.push_document("recover", 0, "plan", state["reviewed_code_sha"], "READY")
        self.wf.agents = SpyAgents()
        result = self.wf.reconcile("document")
        self.assertEqual(result["phase"], "WAITING_DOCUMENT")
        self.assertIsNone(result["pending"])
        self.assertEqual(self.wf.agents.request_calls, 0)

    def test_typed_quota_switches_to_web_once(self):
        class QuotaAgents(SpyAgents):
            providers = []
            def request(self, provider, *args):
                self.providers.append(provider)
                if provider == "native":
                    return workflow.Result(1, '{"type":"turn.failed","error":{"code":"usage_limit_reached"}}')
                return super().request(provider, *args)
        self.wf.agents = QuotaAgents()
        self.wf.init("quota", "goal")
        result = self.wf.step()
        self.assertEqual(result["provider"], "web")
        self.assertEqual(result["phase"], "PLANNING")
        result = self.wf.step()
        self.assertEqual(result["phase"], "WAITING_DOCUMENT")
        self.assertEqual(self.wf.agents.providers, ["native", "web"])

    def test_web_quota_waits_and_does_not_repeat(self):
        class QuotaAgents(SpyAgents):
            def request(self, *args):
                self.request_calls += 1
                return workflow.Result(1, '{"type":"error","message":"You\'ve hit your usage limit. Try later."}')
        self.wf.agents = QuotaAgents()
        self.wf.init("webquota", "goal", review_existing=True)
        self.assertEqual(self.wf.step()["phase"], "WAITING_QUOTA")
        self.wf.step()
        self.assertEqual(self.wf.agents.request_calls, 1)

    def test_network_error_does_not_switch_to_web(self):
        class NetworkAgents(SpyAgents):
            def request(self, *args):
                return workflow.Result(1, '{"type":"turn.failed","error":{"code":"network_error","message":"429 usage limit maybe"}}')
        self.wf.agents = NetworkAgents()
        self.wf.init("network", "goal")
        state = self.wf.step()
        self.assertEqual(state["phase"], "NEEDS_INPUT")
        self.assertEqual(state["provider"], "native")

    def test_document_symlink_is_rejected(self):
        state = self.wf.init("symlink", "goal")
        rel = "workflow-runs/symlink/plan.md"
        target = self.agent_repo / rel
        target.parent.mkdir(parents=True)
        target.symlink_to("../../README.md")
        git(self.agent_repo, "add", rel)
        git(self.agent_repo, "commit", "-m", "symlink document")
        git(self.agent_repo, "push", "origin", "main")
        with self.assertRaisesRegex(workflow.WorkflowError, "regular Markdown"):
            self.wf.validate_document(state)

    def test_changed_document_is_not_dispatched(self):
        state = self.wf.init("changed", "goal")
        self.push_document("changed", 0, "plan", state["reviewed_code_sha"], "READY")
        self.wf.save(state, "WAITING_DOCUMENT")
        self.assertEqual(self.wf.step()["phase"], "READY_TO_IMPLEMENT")
        self.push_document("changed", 0, "plan", state["reviewed_code_sha"], "READY", "Different instructions")
        self.wf.agents = SpyAgents()
        result = self.wf.step()
        self.assertEqual(result["phase"], "NEEDS_INPUT")
        self.assertEqual(self.wf.agents.implement_calls, 0)

    def test_document_commit_is_accepted_when_only_document_changes(self):
        state = self.wf.init("docs1", "add a feature")
        reviewed = state["reviewed_code_sha"]
        self.push_document("docs1", 0, "plan", reviewed, "READY")
        document = self.wf.validate_document(state)
        self.assertEqual(document["metadata"]["status"], "READY")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), document["remote_head"])

    def test_code_commit_after_reviewed_sha_is_rejected(self):
        state = self.wf.init("stale1", "add a feature")
        self.push_document("stale1", 0, "plan", state["reviewed_code_sha"], "READY")
        self.commit_and_push(self.agent_repo, "app.py", "value = 1\n", "change code after review")
        with self.assertRaisesRegex(workflow.WorkflowError, "Code changed after review"):
            self.wf.validate_document(state)

    def test_missing_document_leaves_state_waiting_for_document(self):
        self.wf = workflow.Workflow(self.config, agents=SpyAgents())
        state = self.wf.init("missing1", "add a feature")
        waiting = self.wf.step()
        self.assertEqual(waiting["phase"], "WAITING_DOCUMENT")
        # A completed request without a Git document cannot advance the workflow.
        received = self.wf.step()
        self.assertEqual(received["phase"], "WAITING_DOCUMENT")
        self.assertIn("has not been pushed", received["detail"])

    def test_wrong_remote_is_rejected_before_document_or_agent_actions(self):
        config = workflow.Config(repo=str(self.repo), remote_url=str(self.root / "other.git"),
                                 branch="main", test_command=["true"])
        bad = workflow.Workflow(config)
        with self.assertRaisesRegex(workflow.WorkflowError, "origin URL"):
            bad.init("wrong1", "goal")

    def test_dirty_worktree_is_preserved_and_rejected(self):
        state = self.wf.init("dirty1", "goal")
        marker = self.repo / "uncommitted.txt"
        marker.write_text("keep me")
        result = self.wf.step()
        self.assertEqual(result["phase"], "NEEDS_INPUT")
        self.assertTrue(marker.exists())
        self.assertIn("Working tree is dirty", result["detail"])

    def test_diverged_remote_does_not_overwrite_local_commit(self):
        self.wf.init("diverge1", "goal")
        (self.repo / "local.txt").write_text("local\n")
        git(self.repo, "add", "local.txt")
        git(self.repo, "commit", "-m", "local unpushed")
        local_head = git(self.repo, "rev-parse", "HEAD")
        self.commit_and_push(self.agent_repo, "remote.txt", "remote\n", "remote change")
        result = self.wf.step()
        self.assertEqual(result["phase"], "NEEDS_INPUT")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), local_head)
        self.assertIn("diverged or local commits are unpushed", result["detail"])

    def test_existing_document_prevents_duplicate_agent_request(self):
        state = self.wf.init("repeat1", "goal")
        self.push_document("repeat1", 0, "plan", state["reviewed_code_sha"], "READY")
        spy = SpyAgents()
        wf = workflow.Workflow(self.config, agents=spy)
        # The initialized state already exists at this repo's Git common dir.
        result = wf.step()
        self.assertEqual(result["phase"], "WAITING_DOCUMENT")
        self.assertEqual(spy.request_calls, 0)

    def test_lock_conflict_is_reported(self):
        with self.wf.lock():
            with self.assertRaisesRegex(workflow.WorkflowError, "Another workflow owns"):
                with self.wf.lock():
                    self.fail("second lock unexpectedly acquired")


class SpyAgents:
    def __init__(self):
        self.request_calls = 0
        self.implement_calls = 0

    def request(self, *args):
        self.request_calls += 1
        return workflow.Result(0, '{"type":"turn.completed"}\n')


class HappyPathAgents:
    def __init__(self, fixture):
        self.fixture = fixture
        self.request_calls = 0
        self.implement_calls = 0
        self.requested = []

    def request(self, provider, prompt, logbase, stop_file):
        self.request_calls += 1
        self.requested.append(provider)
        git(self.fixture.agent_repo, "pull", "--ff-only")
        state = self.fixture.wf.load()
        if state["kind"] == "plan":
            self.fixture.push_document(state["run_id"], 0, "plan", state["reviewed_code_sha"], "READY",
                                       "Add tested feature")
        else:
            self.fixture.push_document(state["run_id"], state["iteration"], "review",
                                       state["reviewed_code_sha"], "PASS", "Không cần sửa")
        return workflow.Result(0, '{"type":"turn.completed"}\n')

    def implement(self, prompt, conversation_id, logbase, stop_file):
        self.implement_calls += 1
        path = self.fixture.repo / "feature.py"
        path.write_text("value = 42\n")
        git(self.fixture.repo, "add", "feature.py")
        git(self.fixture.repo, "commit", "-m", "implement feature")
        git(self.fixture.repo, "push", "origin", "main")
        receipt = {"event": "result", "result": {"status": "SUCCESS", "conversation_id": "conversation_1"}}
        return workflow.Result(0, json.dumps(receipt) + "\n")


class EndToEndTests(LocalRepos):
    def test_plan_implement_review_pass_reaches_done_and_repeated_step_is_idle(self):
        self.config.test_command = ["python3", "-B", "-c", "from feature import value; assert value == 42"]
        agents = HappyPathAgents(self)
        self.wf = workflow.Workflow(self.config, agents=agents)
        state = self.wf.init("happy1", "add feature")
        self.assertEqual(state["phase"], "PLANNING")
        phases = [self.wf.step()["phase"] for _ in range(5)]
        self.assertEqual(phases, ["WAITING_DOCUMENT", "READY_TO_IMPLEMENT", "REVIEWING",
                                  "WAITING_DOCUMENT", "DONE"])
        self.assertEqual(agents.request_calls, 2)
        self.assertEqual(agents.implement_calls, 1)
        done = self.wf.step()
        self.assertEqual(done["phase"], "DONE")
        self.assertEqual(agents.request_calls, 2)
        self.assertEqual(agents.implement_calls, 1)
        self.assertEqual(done["implementations"], 1)
        self.assertEqual(len(done["consumed"]), 2)


class ProcessAndAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stop_file = self.root / "stop"
        self.runner = workflow.ProcessRunner()

    def tearDown(self):
        self.temp.cleanup()

    def run_process(self, script, timeout=2):
        return self.runner.run(["python3", "-c", script], cwd=self.root, input_text="", timeout=timeout,
                               logbase=self.root / ("log-" + str(time.monotonic_ns())), stop_file=self.stop_file)

    def test_process_timeout_terminates_child(self):
        result = self.run_process("import time; time.sleep(10)", timeout=0.2)
        self.assertEqual(result.reason, "timeout")
        self.assertIsNotNone(result.returncode)

    def test_stop_file_terminates_child(self):
        timer = threading.Timer(0.2, self.stop_file.touch)
        timer.start()
        try:
            result = self.run_process("import time; time.sleep(10)", timeout=3)
        finally:
            timer.cancel()
        self.assertEqual(result.reason, "stop requested")
        self.assertIsNotNone(result.returncode)

    def test_quota_requires_structured_error_event(self):
        self.assertFalse(workflow.quota_error("The prose says usage_limit_reached; HTTP 429."))
        self.assertFalse(workflow.quota_error('{"type":"assistant.message","text":"insufficient_quota"}'))
        self.assertTrue(workflow.quota_error('{"type":"turn.failed","error":{"code":"usage_limit_reached"}}'))
        self.assertTrue(workflow.quota_error('{"type":"error","error":{"codexErrorInfo":"usageLimitExceeded"}}'))
        self.assertFalse(workflow.quota_error('{"type":"item.completed","item":{"type":"agent_message","text":"You\'ve hit your usage limit."}}'))
        self.assertTrue(workflow.quota_error('{"type":"error","message":"You\'ve hit your usage limit. Try later."}'))

    def test_timeout_stops_descendants_too(self):
        marker = self.root / "should-not-exist"
        child = f"import time; from pathlib import Path; time.sleep(0.7); Path({str(marker)!r}).touch()"
        parent = "import subprocess,time; subprocess.Popen(['python3','-c'," + repr(child) + "]); time.sleep(10)"
        self.run_process(parent, timeout=0.2)
        time.sleep(0.8)
        self.assertFalse(marker.exists())

    def test_expired_total_deadline_prevents_process_start(self):
        self.runner.deadline = time.monotonic() - 1
        marker = self.root / "not-started"
        result = self.run_process(f"from pathlib import Path; Path({str(marker)!r}).touch()")
        self.assertEqual(result.reason, "timeout")
        self.assertFalse(marker.exists())

    def test_agy_prompt_is_json_on_stdin_and_never_shell_interpreted(self):
        class CaptureRunner:
            def run(self, argv, **kwargs):
                self.argv, self.kwargs = argv, kwargs
                return workflow.Result(0, "")
        capture = CaptureRunner()
        cfg = workflow.Config(repo=str(self.root), remote_url="local", agy_command=["agy", "--profile", "test"])
        agents = workflow.Agents(cfg, capture)
        malicious = "$(touch SHOULD_NOT_EXIST); `whoami`; ' ; echo pwned"
        agents.implement(malicious, "conv-1", self.root / "run", self.stop_file)
        self.assertEqual(capture.argv[:2], ["agy", "--profile"])
        self.assertEqual(capture.argv[-2:], ["--conversation", "conv-1"])
        request = json.loads(capture.kwargs["input_text"])
        self.assertEqual(request["message"]["content"], malicious)
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())
        self.assertFalse(any("pwned" in arg for arg in capture.argv))
