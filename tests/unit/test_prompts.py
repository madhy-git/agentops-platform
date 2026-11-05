"""Prompt release discipline: changing a released prompt's text requires a version bump.

RELEASED maps version -> content hash. When you edit prompts/triage.v1.md:
  1. bump `version` in its front matter,
  2. add the new version and its hash here (the failure message prints it).
"""

from agentops import prompts

RELEASED = {"triage": {"1.0.0": "7e4c3d36ad29"}}


def test_released_prompt_text_unchanged_for_its_version():
    p = prompts.load("triage")
    expected = RELEASED["triage"].get(p.version)
    assert expected is not None, f"unreleased version {p.version}; add it with hash {p.sha}"
    assert p.sha == expected, f"text of {p.version} changed (now {p.sha}); bump the version"
