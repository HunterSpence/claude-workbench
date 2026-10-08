import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import error_mine as em


def turn(tid, name, inp, err_text, ts):
    use = {"timestamp": ts, "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}
    res = {"timestamp": ts, "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": True,
                                                     "content": [{"type": "text", "text": err_text}]}]}}
    return json.dumps(use) + "\n" + json.dumps(res) + "\n"


class ErrorMineTest(unittest.TestCase):
    def test_mine_and_cluster(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "proj", "s1", "subagents"))
            with open(os.path.join(root, "proj", "s1.jsonl"), "w") as f:
                f.write(turn("a", "Bash", {"command": "ls /x"}, "ls: cannot access '/x/1': No such file or directory", "2026-01-01T00:00:00Z"))
                f.write(turn("b", "Bash", {"command": "ls /y"}, "ls: cannot access '/y/22': No such file or directory", "2026-01-02T00:00:00Z"))
                f.write(json.dumps({"message": {"content": [{"type": "tool_result", "tool_use_id": "c", "is_error": False, "content": "fine"}]}}) + "\n")
                f.write("not json at all\n")
            with open(os.path.join(root, "proj", "s1", "subagents", "x.jsonl"), "w") as f:
                f.write(turn("d", "WebFetch", {"url": "u"}, "connect ECONNREFUSED alpha.example:443", "2026-02-01T00:00:00Z"))
                f.write(turn("e", "WebFetch", {"url": "u"}, "connect ECONNREFUSED beta.example:443", "2026-02-02T00:00:00Z"))
            total, errors = em.mine(root)
            self.assertEqual(total, 4)
            self.assertEqual(errors[0]["tool"], "Bash")
            self.assertEqual(errors[0]["input"], "command=ls /x")
            self.assertTrue(errors[-1]["subagent"])
            clusters = em.cluster(errors, since="2026-02-01")
            self.assertEqual(len(clusters), 3, clusters)            # two ls errors merge; two hosts stay apart
            self.assertEqual(sorted(c["count"] for c in clusters), [1, 1, 2])
            self.assertEqual(clusters[0]["recent"], 1)               # recent clusters rank first
            with tempfile.TemporaryDirectory() as out:
                self.assertEqual(em.main(["--transcripts", root, "--out", out]), 0)
                self.assertTrue(os.path.exists(os.path.join(out, "clusters.json")))


if __name__ == "__main__":
    unittest.main()
