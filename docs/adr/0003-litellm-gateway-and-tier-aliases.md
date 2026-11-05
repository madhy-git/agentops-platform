# ADR 0003: LiteLLM gateway with tier aliases

- **Status:** accepted
- **Date:** 2026-11-04
- **Phase:** 0

## Context
The router chooses a capability tier. The concrete model behind each tier will change (provider pricing, deprecations, the Bedrock move in Phase 6). Hard-coding provider model ids in the router couples cost policy to vendor naming.

## Options considered
| Option | For | Against |
|---|---|---|
| Provider SDKs called directly | No extra hop | Every provider change is a code change; no central budget or key control |
| LiteLLM proxy with aliases `agentops-tier1/2/3` | One OpenAI-compatible API; swap providers in config; budgets, keys and fallbacks centrally | One more service to run; another layer that can fail |

## Decision
The app only knows tier aliases. `deploy/litellm/config.yaml` maps each alias to a real model. The app's own fallback chain stays (it handles *capability*, going upward only); LiteLLM may add provider-level fallbacks for the same tier.

## Consequences
- Changing provider is a config PR with no Python change.
- The OpenAI client in `llm.py` has `max_retries=0`, so retries aren't stacked across two layers.
- Offline mode bypasses LiteLLM entirely, so CI needs neither keys nor the proxy.
