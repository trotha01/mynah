# HANDOFF (todo: Test mynah PR 4, speakd deadlock fix 534f87f)

## Objective
Test trotha01/mynah PR 4 locally without touching the live speakd; report in ~/org/tasks/mynah-pr4-test/REPORT.org. Do not merge, comment or install without Trevor's yes.

## Done
- Report written: ~/org/tasks/mynah-pr4-test/REPORT.org (verdict: do not merge yet).
- Tests: 25/25 audiowatch, whole suite ok, real CoreAudio stream test, native-stuck exec harness, isolated real speakd 6 cycles (Trevor approved audible 'Test.'), merge checks (PR1 conflicts with PR2 in listen.py; PR4 ok with 3+2 and with 1).
- Defect: installed mlx-audio is 0.5.6 (PR assumed 0.6.4): after a mid-reply underrun the PR leaves a stream running and starts a 2nd. Candidate fix (TappedPlayer.start_stream guard) passes in scratch.
- Live daemon changed pid 21022 -> 64911 (not by these tests: Trevor's Right Option tap at 20:58:30, wake() execs and logs 'Already running', hook restarted it 21:01:10; voice mode now on). Todo marked blocked for that reason.

## Pending
- Trevor: say whether 'Test.' sounded clipped; decide on PR 4 feedback (author fix), install not done.
- ~/src/mynah has uncommitted companion/engine.js, looks.js (not mine; leave them).

## Next step
Send the PR author the findings (do not comment on the PR myself without Trevor), re-test after the fix with $S/streamtest.py underrun2 (scratchpad), then ask Trevor about the real install.
