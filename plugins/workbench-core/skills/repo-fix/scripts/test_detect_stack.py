import json, os, shutil, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detect_stack as ds  # noqa: E402


def write(root, rel, text=""):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


class DetectStackTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def cmds(self):
        return {(c["role"], c["command"]) for c in ds.detect(self.d)["commands"]}

    def test_node_pnpm(self):
        write(self.d, "package.json", json.dumps({"scripts": {"test": "vitest run", "test:e2e": "playwright test",
                                                              "lint": "eslint .", "typecheck": "tsc --noEmit",
                                                              "build": "vite build", "dev": "vite"}}))
        write(self.d, "pnpm-lock.yaml")
        c = self.cmds()
        for want in [("test", "pnpm test"), ("test", "pnpm test:e2e"), ("lint", "pnpm lint"),
                     ("typecheck", "pnpm typecheck"), ("build", "pnpm build")]:
            self.assertIn(want, c)
        self.assertTrue(any(r == "install" and cmd.startswith("pnpm install --frozen-lockfile") for r, cmd in c))
        self.assertFalse(any("dev" in cmd for _, cmd in c), "dev server is not a check")

    def test_node_npm_ci(self):
        write(self.d, "package.json", json.dumps({"scripts": {"test": "jest"}}))
        write(self.d, "package-lock.json", "{}")
        self.assertIn(("test", "npm run test"), self.cmds())
        self.assertTrue(any(cmd.startswith("npm ci") for r, cmd in self.cmds() if r == "install"))

    def test_python_uv(self):
        write(self.d, "pyproject.toml", "[project]\nname='x'\n[tool.pytest.ini_options]\naddopts='-q'\n[tool.ruff]\nline-length=100\n"
                                        "[tool.mypy]\nstrict=true\n")
        write(self.d, "uv.lock")
        c = self.cmds()
        for want in [("install", "uv sync"), ("test", "uv run pytest"), ("lint", "uv run ruff check ."),
                     ("typecheck", "uv run mypy .")]:
            self.assertIn(want, c)

    def test_python_plain_requirements(self):
        write(self.d, "requirements.txt", "requests\n")
        write(self.d, "tests/test_x.py")
        c = self.cmds()
        self.assertIn(("install", "pip install -r requirements.txt"), c)
        self.assertIn(("test", "python -m pytest"), c)

    def test_make_go_and_ci(self):
        write(self.d, "Makefile", "VAR := 1\ntest: build\n\tgo test ./...\nlint:\n\tgolangci-lint run\nfmt:\n\tgofmt -w .\n")
        write(self.d, "go.mod", "module example.com/x\n")
        write(self.d, ".github/workflows/ci.yml",
              "jobs:\n  t:\n    steps:\n      - uses: actions/checkout@v4\n      - run: make test\n"
              "      - name: lint\n        run: |\n          make lint\n          # comment\n          go vet ./...\n"
              "      - run: echo done\n")
        r = ds.detect(self.d)
        c = {(x["role"], x["command"]) for x in r["commands"]}
        for want in [("test", "make test"), ("lint", "make lint"), ("format", "make fmt"), ("test", "go test ./...")]:
            self.assertIn(want, c)
        self.assertNotIn(("test", "make VAR"), c)
        runs = [x["run"] for x in r["ci"]]
        self.assertEqual(runs, ["make test", "make lint\ngo vet ./...", "echo done"])

    def test_gitlab_script_list(self):
        write(self.d, ".gitlab-ci.yml", "test:\n  script:\n    - npm ci\n    - npm test\nlint:\n  script: [\"npm run lint\"]\n")
        self.assertEqual([x["run"] for x in ds.detect(self.d)["ci"]], ["npm ci", "npm test", "npm run lint"])

    def test_stdlib_unittest_only(self):
        write(self.d, "tools/x/test_x.py")
        self.assertTrue(any(r == "test" and "unittest discover" in c for r, c in self.cmds()))

    def test_nothing(self):
        self.assertEqual(ds.detect(self.d)["commands"], [])
        self.assertEqual(ds.main([self.d]), 0)
        self.assertEqual(ds.main([os.path.join(self.d, "missing")]), 2)

    def test_monorepo_depth_and_skips(self):
        write(self.d, "package.json", json.dumps({"private": True, "workspaces": ["packages/*"]}))
        write(self.d, "packages/web/package.json", json.dumps({"scripts": {"test": "vitest", "lint": "eslint .",
                                                                           "lint:fix": "eslint . --fix"}}))
        write(self.d, "services/api/app/pyproject.toml", "[project]\nname='api'\n[tool.pytest.ini_options]\n")
        write(self.d, "a/b/c/d/package.json", json.dumps({"scripts": {"test": "too-deep"}}))       # depth 4
        write(self.d, "node_modules/dep/package.json", json.dumps({"scripts": {"test": "dep-test"}}))
        write(self.d, "packages/web/dist/package.json", json.dumps({"scripts": {"test": "built"}}))
        rows = {(c["dir"], c["role"], c["command"]) for c in ds.detect(self.d)["commands"]}
        self.assertIn(("packages/web", "test", "npm run test"), rows)
        self.assertIn(("packages/web", "lint", "npm run lint"), rows)
        self.assertIn(("packages/web", "fix", "npm run lint:fix"), rows)
        self.assertNotIn(("packages/web", "lint", "npm run lint:fix"), rows)
        self.assertIn(("services/api/app", "test", "python -m pytest"), rows)
        dirs = {d for d, _, _ in rows}
        self.assertFalse({"a/b/c/d", "node_modules/dep", "packages/web/dist"} & dirs, dirs)

    def test_block_scalar_keeps_cd_and_working_directory(self):
        write(self.d, ".github/workflows/ci.yml",
              "on: [push, pull_request]\njobs:\n  t:\n    steps:\n"
              "      - name: web\n        run: |\n          cd web\n          npm ci\n          npm test\n"
              "      - name: api\n        working-directory: services/api\n        run: pytest -q\n"
              "      - run: >\n          echo one\n          two\n"
              "      - run: npm run e2e\n        working-directory: \"e2e tests\"\n"
              "  u:\n    defaults:\n      run:\n        shell: bash\n    steps:\n      - run: make lint\n")
        self.assertEqual([x["run"] for x in ds.detect(self.d)["ci"]],
                         ["cd web\nnpm ci\nnpm test", "cd services/api && pytest -q", "echo one two",
                          'cd "e2e tests" && npm run e2e', "make lint"])

    def test_gitlab_cd_item_and_quotes(self):
        write(self.d, ".gitlab-ci.yml",
              "test:\n  script:\n    - cd app\n    - npm test -- --grep \"a, b\"\n"
              "lint:\n  script: [\"npm run lint\", 'echo \"x, y\"']\n"
              "say:\n  script: echo \"done\"   # trailing comment\n")
        self.assertEqual([x["run"] for x in ds.detect(self.d)["ci"]],
                         ['cd app && npm test -- --grep "a, b"', "npm run lint", 'echo "x, y"', 'echo "done"'])

    def test_release_workflows_skipped(self):
        write(self.d, ".github/workflows/ci.yml", "on: push\njobs:\n  t:\n    steps:\n      - run: make test\n")
        write(self.d, ".github/workflows/release.yml", "on: push\njobs:\n  r:\n    steps:\n      - run: npm publish\n")
        write(self.d, ".github/workflows/ship.yml", "on:\n  release:\n    types: [published]\njobs:\n  s:\n"
                                                    "    steps:\n      - run: ./ship.sh\n")
        write(self.d, ".github/workflows/tagged.yml", "on:\n  push:\n    tags:\n      - 'v*'\njobs:\n  s:\n"
                                                      "    steps:\n      - run: ./tag.sh\n")
        r = ds.detect(self.d)
        self.assertEqual([x["run"] for x in r["ci"]], ["make test"])
        self.assertEqual(sorted(r["ci_skipped"]), [".github/workflows/release.yml", ".github/workflows/ship.yml",
                                                   ".github/workflows/tagged.yml"])

    def test_pr_template_codeowners_contributing(self):
        write(self.d, ".github/pull_request_template.md", "## What\n")
        write(self.d, "docs/PULL_REQUEST_TEMPLATE/feature.md", "x")
        write(self.d, ".github/CODEOWNERS", "* @acme/team\n")
        write(self.d, "CONTRIBUTING.md", "x")
        d = ds.detect(self.d)["docs"]
        self.assertEqual(d["pr_template"], [".github/pull_request_template.md", "docs/PULL_REQUEST_TEMPLATE/feature.md"])
        self.assertEqual(d["codeowners"], [".github/CODEOWNERS"])
        self.assertEqual(d["contributing"], ["CONTRIBUTING.md"])
        os.makedirs(os.path.join(self.d, "empty"))
        self.assertEqual(ds.detect(os.path.join(self.d, "empty"))["docs"], {"pr_template": [], "codeowners": [], "contributing": []})

    def test_pnpm_workspace_member_inherits_manager(self):
        write(self.d, "package.json", json.dumps({"private": True, "scripts": {"lint": "eslint ."}}))
        write(self.d, "pnpm-lock.yaml")
        write(self.d, "pnpm-workspace.yaml", "packages: ['packages/*']\n")
        write(self.d, "packages/web/package.json", json.dumps({"scripts": {"test": "vitest run", "build": "vite build"}}))
        r = ds.detect(self.d)["commands"]
        web = {(c["role"], c["command"]) for c in r if c["dir"] == "packages/web"}
        self.assertIn(("test", "pnpm test"), web)
        self.assertIn(("build", "pnpm build"), web)
        self.assertFalse(any("npm" in cmd and not cmd.startswith("pnpm") for _, cmd in web), web)
        self.assertFalse(any(role == "install" for role, _ in web), "the member installs from the workspace root")
        self.assertTrue(any(c["role"] == "install" and c["dir"] == "." and c["command"].startswith("pnpm install")
                            for c in r))

    def test_package_manager_field(self):
        write(self.d, "package.json", json.dumps({"packageManager": "yarn@4.1.0", "scripts": {"test": "jest"}}))
        c = self.cmds()
        self.assertIn(("test", "yarn test"), c)
        self.assertTrue(any(r == "install" and cmd.startswith("yarn install") for r, cmd in c))

    def test_defaults_run_working_directory(self):
        write(self.d, ".github/workflows/ci.yml",
              "on: [push]\n"
              "defaults:\n  run:\n    working-directory: web\n"
              "jobs:\n"
              "  api:\n    runs-on: ubuntu-latest\n"
              "    defaults:\n      run:\n        shell: bash\n        working-directory: services/api\n"
              "    steps:\n      - run: ruff check .\n      - run: pytest\n        working-directory: services/api/tests\n"
              "  web:\n    runs-on: ubuntu-latest\n    steps:\n      - run: npm test\n")
        runs = [c["run"] for c in ds.detect(self.d)["ci"]]
        self.assertIn("cd services/api && ruff check .", runs)
        self.assertIn("cd services/api/tests && pytest", runs)
        self.assertIn("cd web && npm test", runs)
        self.assertFalse(any("shell: bash" in r or r.startswith("cd services/api && shell") for r in runs), runs)

    def test_reads_only(self):
        with open(ds.__file__, encoding="utf-8") as f:
            src = f.read()
        for banned in ("subprocess", "os.system", "Popen", "exec("):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()
