---
title: Integration status labels
category: Settings
summary: The four delivery statuses and what each integration's status means.
routes: /settings
---
| Status | Meaning |
| --- | --- |
| Implemented and verified locally | Works on this machine against local components |
| Implemented but externally unverified | Code exists and passes tests against fakes, but has not run against the real provider |
| Verified against a real configured provider | Exercised against the real service with your configuration |
| Not implemented or blocked | Not built, disabled, or blocked by a stated dependency |

A Mock or simulated success never counts as verification of a broker, Zoom, market data or a model. A model counts as verified only after a real model-mode run on this machine (name and digest recorded).
