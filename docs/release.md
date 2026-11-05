# Release management

<!-- LEARNING NOTE: AI behaviour changes come from four places: code, prompts, rules and models.
Each needs a version, a gate and a rollback path. -->

| What changes | Versioned by | Gate | Rollout | Rollback |
|---|---|---|---|---|
| Code | semver in `pyproject.toml` / `agentops.__version__`, `CHANGELOG.md` | CI: lint, types, tests, eval gate | deploy | redeploy previous image |
| Prompt | `version` in front matter + hash test (`tests/unit/test_prompts.py`) | eval gate; shadow run | flag `AGENTOPS_PROMPT_TRIAGE_MAJOR=2` | unset the flag |
| Rules | `version` in `policies/rules.yaml` + released-version test | replay (S6) + eval gate | flag `AGENTOPS_POLICY_FILE=policies/rules-next.yaml` | unset the flag |
| Model behind a tier | LiteLLM config (`deploy/litellm/config.yaml`) | `evals/shadow.py` diff + live eval | config change | revert config |

**Release checklist**
1. `uv run python evals/run_evals.py --report`: gate passes; report saved to `docs/evals/<version>-<mode>.md`.
2. Live mode: run the baseline and the gate; compare against the previous live report's spread.
3. For prompt, rule or model changes: shadow run, then review *every* disagreement.
4. Update `CHANGELOG.md`; bump the version; tag.
5. After deploy: watch the SLO dashboard (`docs/slo.md`) for one error-budget window.
