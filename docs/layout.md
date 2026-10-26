# Repository layout

```
agent_gate/            the package: run_all.py, prepush.py, gate.py, config.py, common.py, __main__.py
agent_gate/checks/     one module per check
bin/stopline           launcher (python3 -I bin/stopline <run|staged|msg|tree|pre-push|gate> ...)
bin/agent-gate         the same launcher under the old name
hooks/                 pre-commit, commit-msg, pre-push, install.sh
examples/              agent-gate.toml, claude-settings.json, demo.sh
scripts/               render_demo_svg.py (docs/demo.svg from the demo), social-preview.html
docs/                  reference documentation
.github/workflows/     ci.yml: the server-side job
rules.toml             each rule, the files that enforce it, and what it does not catch
tests/                 282 unit and end-to-end tests (python3 -m unittest discover -s tests)
agent-gate.toml        the rules stopline applies to its own repository
```
