---
id: POL-FRAUD-02
title: Fraud detection thresholds and rules
classification: confidential
allowed_roles: [fraud_specialist, manager]
version: "2026.3"
---
Wattle Bank (fictional). Confidential: fraud specialists and managers only. Disclosure would help fraudsters evade detection.

Velocity rule. More than five card-not-present transactions within ten minutes triggers a soft block and a fraud specialist review.

Geography rule. A card-present transaction more than 800 kilometres from the previous one within two hours triggers a review.

Mule indicators. New payees added and paid within one hour, followed by a password reset, raise the customer's fraud score by 40 points.
