# Wattle Bank decision rules R1-R7 as policy-as-code (OPA / Rego v1). Phase 7 variant of policies/rules.yaml.
#
# LEARNING NOTES
# - Rego is declarative: there is no "run R1, then R5". The Python engine's ordering ("each rule sees what
#   earlier rules did") becomes explicit layers below: actions -> flags_after -> regulated -> suppression.
#   Writing it this way makes the dependencies visible, which is arguably clearer than file order.
# - Parity with the Python engine is tested on every replay context (tests/unit/test_opa_parity.py). Two
#   implementations of the same policy only help if something proves they agree.
# - Why OPA at all? One policy engine shared by many services and languages, policy bundles deployed
#   separately from code, and decision logs built in. For one Python service, the YAML engine is enough.
package wattle

regulated_actions := {"block_card", "hardship_review", "refund_review", "compensation", "hardship_arrangement"}

action_map := {
	"freeze_card": "block_card",
	"hardship_review": "hardship_review",
	"refund_review": "refund_review",
	"escalate": "escalate",
}

# decisions: one result per context, so a whole replay can be evaluated in a single call.
decisions := [decide(c) | some c in input.contexts]

decide(c) := {
	"fired": fired(c),
	"actions": sort_set(actions(c) - blocked(c)),
	"set_flags": sort_set(new_flags(c)),
	"requires_approval": "R5" in fired(c),
	"suppress_marketing": "R7" in fired(c),
}

# --- layer 1: rules that depend only on the input ---------------------------------------------------------
r1(c) if c.category == "fraud"

r2(c) if c.category == "hardship"

# is_number() guards matter: Rego orders values ACROSS types, so `null < 121` is TRUE. Without the guard an
# unknown transaction age fired R3b and asked for a refund approval. Found by the exhaustive parity test
# (80/2000 contexts differed); Python's engine treats None as "never matches".
r3(c) if {
	c.category == "dispute"
	is_number(c.txn_age_days)
	c.txn_age_days > 120
}

r3b(c) if {
	c.category == "dispute"
	is_number(c.txn_age_days)
	c.txn_age_days < 121
}

r4(c) if c.category == "complaint"

recommended(c) := {action_map[c.recommended_action]} if c.recommended_action in object.keys(action_map)

else := set()

actions(c) := (((recommended(c) | {a | r1(c); some a in {"block_card"}}) | {a | r2(c); some a in {"hardship_review", "hold_collections"}}) | {a | r3(c); some a in {"manual_review"}}) | ({a | r3b(c); some a in {"refund_review"}} | {a | r4(c); some a in {"start_complaint_clock"}})

blocked(c) := {"refund_review"} if r3(c)

else := set()

# --- layer 2: flags after this decision (input flags + flags set by R1/R2/R4) --------------------------------
new_flags(c) := ({f | r1(c); f := "fraud_flag"} | {f | r2(c); f := "hardship_flag"} | {f | r4(c); f := "complaint_open"}) - {f | some f in c.flags}

flags_after(c) := {f | some f in c.flags} | new_flags(c)

# --- layer 3: rules that depend on layers 1-2 ----------------------------------------------------------------
r5(c) if {
	c.role == "officer"
	some a in actions(c) - blocked(c)
	a in regulated_actions
}

r6(c) if {
	is_number(c.risk_score)
	c.risk_score > 0.5
	not "hardship_flag" in flags_after(c)
}

r7(c) if {
	some f in flags_after(c)
	f in {"fraud_flag", "hardship_flag", "complaint_open", "cooling_off"}
}

fired(c) := [id |
	some id in ["R1", "R2", "R3", "R3b", "R4", "R5", "R6", "R7"]
	rule_fires(id, c)
]

rule_fires("R1", c) if r1(c)

rule_fires("R2", c) if r2(c)

rule_fires("R3", c) if r3(c)

rule_fires("R3b", c) if r3b(c)

rule_fires("R4", c) if r4(c)

rule_fires("R5", c) if r5(c)

rule_fires("R6", c) if r6(c)

rule_fires("R7", c) if r7(c)

sort_set(s) := sort([x | some x in s])
