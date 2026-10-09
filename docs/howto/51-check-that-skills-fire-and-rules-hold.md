# Check that skills fire and rules hold

Automates it: py -3 <KIT>/tools/skill-probe/skill_probe.py and py -3 <KIT>/tools/rules-quiz/rules_quiz.py

## When to use
You wrote or changed a skill and want to know whether Claude starts it when it should and leaves it alone when it should not,
or you wrote or changed a rule and want to know whether a fresh session obeys it. Both checks run offline on your machine and
neither prints your prompts. The skill probe reads transcripts you already have. The rules quiz uses twelve short model calls
on your plan, one per scenario, and the grading itself calls no model. `<KIT>` is the kit folder (guide 01).

## Steps
**Skills**
1. Write a probe file, for example `probe.json`: for each skill, patterns for prompts that should start it and for near
   misses that should not. Take the wording from things you really type.
   ```
   {"version": 1, "skills": {"diagram": {
     "should": ["draw a (diagram|flowchart)", "sketch the architecture"],
     "should_not": ["what is a flowchart", "explain this diagram"]}}}
   ```
2. Use Claude Code normally for a while with the skill installed, so there are transcripts to read. Aim for at least five
   matching prompts on each side.
3. Run the probe. It reads the `projects` folder of your Claude configuration folder unless you pass `--transcripts`:
   ```
   py -3 <KIT>/tools/skill-probe/skill_probe.py --spec probe.json
   ```
4. Read each skill's block. "should" rate is the share of matching prompts that led to a `Skill` call for that skill, and the
   ids listed are the prompts that did not. The "should_not" rate is the share of near misses that wrongly started it. The
   targets are 80 percent or more and 20 percent or less. Under five prompts the tool gives no verdict.
5. Fix the wording, then start a new session and collect more transcripts. A skill that is missed: lead the description with
   what the user would say and add a `when_to_use` line beginning "ALWAYS load before" (`docs/AUTHORING.md` section 1). A
   skill that fires on near misses: add them under "NOT for" in the description.

**Rules**
6. Print the scenarios:
   ```
   py -3 <KIT>/tools/rules-quiz/rules_quiz.py list
   ```
7. Put each prompt, as written, to a fresh session with no tools, from the folder whose rules you want to test, and save the
   reply as `<id>.txt` in one folder. A scripted version in PowerShell (twelve short model calls):
   ```
   $q = py -3 <KIT>/tools/rules-quiz/rules_quiz.py list --json | ConvertFrom-Json
   New-Item -ItemType Directory -Force answers | Out-Null
   foreach ($s in $q.scenarios) { claude -p --tools "" --no-session-persistence $s.prompt | Set-Content -Encoding utf8 "answers/$($s.id).txt" }
   ```
8. Grade the replies:
   ```
   py -3 <KIT>/tools/rules-quiz/rules_quiz.py grade --answers answers
   ```
9. Under nine of ten (11 of the 12) the tool says to reword the rule and names each failed scenario and the rule it tests. Open
   the failed reply, and reword that rule: one imperative with its reason, as `docs/AUTHORING.md` section 5 describes. Start a
   new session and run steps 7 and 8 again.

## Verify
- The probe shows at least five prompts on each side for the skill you changed, and its verdict is `ok` or names a fix you
  made and re-measured.
- Test the quiz itself once: save the one word "Done." as every reply and grade it. Every scenario must fail.
- The quiz grade is 11 of 12 or better after the rewording, in a new session.
- No prompt or reply text appears in either tool's output, only counts, ids and pattern numbers.

## Common failures
- **"too few matching prompts to judge":** the patterns are narrower than your real wording, or there are too few sessions.
  Widen the patterns or use the skill for longer; do not read a rate from three prompts.
- **The skill clearly ran but the probe counts none:** you started it with a slash command, which is not the model's decision and
  is not counted. A skill the model chose shows as a `Skill` tool call in the transcript.
- **A reply that is right fails the quiz:** the patterns are a coarse first filter and miss some wordings. Read the reply
  before touching the rule. If the reply was right, widen the pattern in your copy of the script.
- **The quiz passes with the rule deleted:** the session was not running your rules, or the scenario is answered correctly
  from general habit. Run it once with the rule removed in a scratch folder: if it still passes, the scenario does not test
  that rule.
- **The model tried to act instead of answering:** the session had tools. Use `--tools ""` as above, or paste the prompt into a
  session in a scratch folder and decline any action it asks to take.
- **Project rules did not apply:** they load from the folder the session starts in. Run the quiz from that folder.
