"""Model factory: turns a router decision into something PydanticAI can run.

LEARNING NOTES
- offline: a deterministic FunctionModel (agent.offline_model). It drives the *real* agent loop
  (tool calls, structured output, validation), so CI exercises the pipeline without API keys.
  Its scores say nothing about model quality; see LEARNING_TRACKER A3/A11.
- live: an OpenAI-compatible client pointed at the LiteLLM gateway. The model name is the tier
  alias; LiteLLM maps it to Anthropic, Bedrock or Azure (deploy/litellm/config.yaml).
- Timeouts and retries: `max_retries=0` on the client because *our* fallback chain owns retry
  policy (service._run_with_fallback). Two retry layers stacked on top of each other multiply
  latency during an outage, a classic resilience mistake.
"""

from __future__ import annotations

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .config import settings
from .router import ModelSpec


def live_model(spec: ModelSpec, timeout_s: float = 30.0) -> Model:
    from openai import AsyncOpenAI

    s = settings()
    client = AsyncOpenAI(base_url=s.litellm_base_url, api_key=s.litellm_api_key, timeout=timeout_s, max_retries=0)
    return OpenAIChatModel(spec.name, provider=OpenAIProvider(openai_client=client))


def model_for(spec: ModelSpec) -> Model:
    from .agent import offline_model

    return live_model(spec) if settings().live else offline_model()
