import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from ithutecode.git_credentials import credential_environment
from ithutecode.git_transport import GitTransport

REMOTE = "https://github.com/example/project.git"

class CredentialTests(unittest.TestCase):
    def test_scoped_header(self):
        calls = []
        def provider(repo):
            calls.append(repo)
            return "fake_token"
        env = credential_environment(42, REMOTE, provider)
        self.assertEqual(calls, [42])
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "http." + REMOTE + ".extraHeader")
        encoded = env["GIT_CONFIG_VALUE_0"].split()[-1]
        self.assertEqual(base64.b64decode(encoded), b"x-access-token:fake_token")
        self.assertEqual(env["GIT_CONFIG_VALUE_1"], "")
        self.assertEqual(env["GIT_CONFIG_VALUE_2"], "false")

    def test_wrong_host(self):
        with self.assertRaises(ValueError):
            credential_environment(42, "https://example.org/repo.git", lambda _: "fake")

    def test_invalid_repository(self):
        with self.assertRaises(ValueError):
            credential_environment(True, REMOTE, lambda _: "fake")

    def test_invalid_tokens(self):
        for token in ("", "token\nextra", None, "x"*2049):
            with self.subTest(token=token), self.assertRaises(ValueError):
                credential_environment(42, REMOTE, lambda _: token)

    def test_network_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            transport = GitTransport(root, 42, REMOTE, token_provider=lambda _: "fake_token")
            with patch("ithutecode.git_transport.subprocess.run", return_value=SimpleNamespace(stdout=b"ok")) as run:
                transport._git("rev-parse", "HEAD")
                self.assertNotIn("GIT_CONFIG_VALUE_0", run.call_args.kwargs["env"])
                transport._git("ls-remote", "--", REMOTE)
                self.assertIn("GIT_CONFIG_VALUE_0", run.call_args.kwargs["env"])
                self.assertNotIn("fake_token", str(run.call_args.args))

    def test_no_credentials_for_local_remote(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            with self.assertRaises(ValueError):
                GitTransport(root, 42, root, local_test=True, token_provider=lambda _: "fake")
