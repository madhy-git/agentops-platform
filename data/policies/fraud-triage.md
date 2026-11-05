---
id: POL-FRAUD-01
title: Frontline fraud triage procedure
classification: internal
allowed_roles: [officer, manager]
version: "2026.2"
---
Wattle Bank (fictional). Use this procedure when a customer reports a stolen card, an unauthorised transaction or a scam.

Step one. Recommend an immediate card block. The block is a regulated action: it is executed only after a fraud specialist approves it, or automatically by the decision service when rule R1 fires and policy allows.

Step two. Never ask the customer for a full card number, PIN, or one-time passcode. Scammers impersonate bank staff to collect these.

Step three. Suppress all marketing contact for the customer while the fraud flag is active. Route the case to the fraud queue with reason code FRAUD_SUSPECTED.

Scams. If the customer was tricked into making a payment themselves, record it as an authorised push payment scam. Recovery is attempted but not guaranteed. Do not promise a refund.
