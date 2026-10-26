"""One module per rule. Each module has run(...) returning a list of problem strings; an empty list is green."""
from . import (check_secrets, check_commits, check_signatures, check_language, check_supply_chain, check_pinned_models,
               check_hidden_text, check_telemetry_flags, check_core_sync, check_changes, check_required_text, check_gate_wiring)

# name in agent-gate.toml -> module; history checks judge base..HEAD, tree checks judge the tracked files of the tree
HISTORY = {"secrets": check_secrets, "commits": check_commits, "signatures": check_signatures, "language": check_language}
TREE = {"supply_chain": check_supply_chain, "pinned_models": check_pinned_models, "hidden_text": check_hidden_text,
        "telemetry_flags": check_telemetry_flags, "core_sync": check_core_sync, "changes": check_changes,
        "required_text": check_required_text, "gate_wiring": check_gate_wiring}
ALL = {**HISTORY, **TREE}
