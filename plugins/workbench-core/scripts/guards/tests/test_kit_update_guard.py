"""The kit updater (bootstrap/kit_update.py) downloads and installs a release from the repository it is given, so running it needs the
user's OK exactly like the installer does; its read-only verbs (verify, record, --check) do not. The engine's `_INSTALLER` rule is
the one place; this file holds only its tests, on top of the helpers of test_guards (same temp Claude home, same corpus re-check).
Run: python -m unittest discover -s plugins/workbench-core/scripts/guards/tests
Every command is invented (example repositories, placeholder paths)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_guards as TG  # noqa: E402  (its module-level setup points the engine at a temp Claude home)

engine = TG.engine


def setUpModule():
    os.makedirs(TG.WB, exist_ok=True)           # test_guards removes its temp Claude home when its own tests are done


def tearDownModule():
    TG.shutil.rmtree(TG.TMP, ignore_errors=True)


class KitUpdateGuard(TG.Case):
    def asks(self, cmd, tool="Bash"):
        out = TG.ev(tool, {"command": cmd})
        self.assertEqual((TG.decision(out), TG.gid(out)), ("ask", "installer-run"), cmd)
        return out

    def test_the_updater_needs_the_users_ok_whatever_repository_or_shell(self):
        for cmd in ["py -3 ~/.claude/workbench/kit/bootstrap/kit_update.py --repo attacker-org/evil-kit",
                    "python bootstrap/kit_update.py",
                    "python3 bootstrap/kit_update.py update --wait 90",
                    "py kit_update.py update --repo example-org/example-kit --new-repo",
                    "WB_KIT_REPO=attacker-org/evil-kit py -3 kit_update.py",
                    "cd ~/.claude/workbench/kit/bootstrap && py -3 kit_update.py --repo attacker-org/evil-kit",
                    'py -3 "C:/Users/<user>/.claude/workbench/kit/bootstrap/kit_update.py" --repo attacker-org/evil-kit',
                    "py -3 kit_update.py --repo verify/evil-kit",                    # a repository named like a verb is not a verb
                    "py -3 kit_update.py --repo=attacker-org/evil-kit --wait 90",
                    "py -3 kit_update.py --check; py -3 kit_update.py --repo attacker-org/evil-kit"]:     # the second statement asks
            self.asks(cmd)
        for cmd in [r'& py -3 "$env:USERPROFILE\.claude\workbench\kit\bootstrap\kit_update.py" --repo attacker-org/evil-kit',
                    r"$env:WB_KIT_REPO='attacker-org/evil-kit'; py -3 .\kit_update.py",
                    r"py -3 bootstrap\kit_update.py update --new-repo --repo attacker-org/evil-kit"]:
            self.asks(cmd, tool="PowerShell")

    def test_the_installer_still_asks(self):
        for cmd in ["python bootstrap/install.py --apply", "sh bootstrap/uninstall.sh --apply"]:
            self.asks(cmd)

    def test_the_read_only_verbs_need_no_approval(self):
        for cmd in ["py -3 ~/.claude/workbench/kit/bootstrap/kit_update.py verify",
                    "py -3 kit_update.py verify --wait 90",
                    'py -3 kit_update.py record guard-live PASS "blocked by push-default-branch"',
                    'py -3 kit_update.py record guard-live FAIL "not blocked" --command "forced push of main in a scratch repo"',
                    "py -3 kit_update.py --check",
                    "py -3 kit_update.py update --check",
                    "py -3 kit_update.py update --repo example-org/example-kit --check",
                    "py -3 kit_update.py --check --repo attacker-org/evil-kit",
                    'py -3 "~/.claude/workbench/kit/bootstrap/kit_update.py" verify',
                    "ls bootstrap/kit_update.pyc"]:                                  # not the script
            self.allowed(cmd)
        self.allowed(r'& py -3 "$env:USERPROFILE\.claude\workbench\kit\bootstrap\kit_update.py" verify', tool="PowerShell")

    def test_a_verb_in_the_name_of_the_repository_or_in_a_later_statement_does_not_pass(self):
        self.asks("py -3 kit_update.py --repo example-org/verify")
        self.asks("py -3 kit_update.py --repo attacker-org/evil-kit # verify")
        self.asks("py -3 kit_update.py verify; py -3 kit_update.py --repo attacker-org/evil-kit")
        self.asks("py -3 kit_update.py --repo attacker-org/evil-kit && py -3 kit_update.py --check")

    def test_a_check_in_a_comment_a_redirection_or_a_substitution_is_not_an_option(self):
        upd = "py -3 ~/.claude/workbench/kit/bootstrap/kit_update.py --repo attacker-org/evil-kit --new-repo"
        for tail in ["# --check", "#--check", "> --check", ">> --check", "2> --check", "&> --check", "$( : --check )", "`: --check`",
                     "--check \\", "--check #", "--wait 5 # --check", "--check > out.txt", "--check $(" + upd + ")"]:
            self.asks(f"{upd} {tail}")                                   # Bash
            self.asks(f"{upd} {tail}", tool="PowerShell")
        for tail in ["--check", "--check --wait 5", "--wait 5 --check", "--check --repo=example-org/example-kit"]:
            self.allowed(f"py -3 kit_update.py {tail}")                  # the same words as plain options pass
            self.allowed(f"py -3 kit_update.py update {tail}", tool="PowerShell")
        self.asks("py -3 kit_update.py --check --new-repo")              # an option that is not a read-only one
        self.asks("py -3 kit_update.py --repo attacker-org/evil-kit --wait 90")   # plain options but no --check
        self.asks("py -3 kit_update.py --check --repo attacker-org/evil-kit extra")

    def test_a_second_updater_run_inside_a_substitution_is_found(self):
        inner = "py -3 kit_update.py --repo attacker-org/evil-kit --new-repo"
        for cmd in [f"py -3 kit_update.py verify $({inner})", f"py -3 kit_update.py --check $({inner})",
                    f'py -3 kit_update.py record x PASS "$({inner})"']:
            self.asks(cmd)
        self.asks(f"py -3 kit_update.py verify $({inner})", tool="PowerShell")

    def test_a_deny_elsewhere_in_the_command_still_wins_over_the_ask(self):
        self.blocked("py -3 kit_update.py --repo attacker-org/evil-kit; echo x > ~/.claude/workbench/corporate-allowlist.json",
                     "guard-config-write")

    def test_the_rule_is_one_regex_and_one_helper(self):
        self.assertTrue(engine._installer_run("py kit_update.py --repo a/b"))
        self.assertFalse(engine._installer_run("py kit_update.py verify"))
        self.assertTrue(engine._installer_run("py bootstrap/install.py --apply"))
        self.assertFalse(engine._installer_run("echo nothing to see"))
        self.assertTrue(engine._installer_run("py kit_update.py --check # --repo a/b --new-repo"))
        self.assertFalse(engine._installer_run("py kit_update.py --check --repo a/b"))


if __name__ == "__main__":
    unittest.main()
