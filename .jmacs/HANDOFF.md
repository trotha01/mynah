# Handoff
## Objective
Org report docs/voice-interruption-research.org: how voice products/libs do barge-in + proposed speakd API.
## Done
- Branch cloud/voice-apis. `kb` CLI not in this cloud container (findings 96/97/103 unreadable; cited via docs/voice-conversation-plan.md and README instead).
- Read speakd.py/listen.py/aec.py/lipsync.py: mynah already has AEC3 tap, Endpointer barge-in, token-cancel stop(), lipsync word timeline + played-sample anchor.
- Launched 3 research agents (realtime APIs, frameworks, local/Apple).
## Pending
- Collect agent results, write report, PR + merge to main.
## Next step
Write docs/voice-interruption-research.org from agent results.
