"""The instant `say` tier (MYNAH_FIRST_SENTENCE / MYNAH_TTS=say-only). A fake `say` script stands in for macOS say, so this runs
anywhere; Kokoro is a stub. What it cannot check is real audio: see the PR for the by-ear checks."""
import os
import stat
import time

import pytest

from mynah import speakd


def test_split_simple():
    assert speakd.split_first_sentence("Done. All tests pass. Next step.") == ("Done.", "All tests pass. Next step.")


def test_split_question_and_quote():
    assert speakd.split_first_sentence('Did you say "stop?" Yes.') == ('Did you say "stop?"', "Yes.")


def test_split_skips_abbreviations_and_list_numbers():
    assert speakd.split_first_sentence("Use e.g. a flag. Then go.") == ("Use e.g. a flag.", "Then go.")
    assert speakd.split_first_sentence("See Dr. Smith today. Ok.") == ("See Dr. Smith today.", "Ok.")
    assert speakd.split_first_sentence("1. First. Second.") == ("1. First.", "Second.")


def test_split_newline_is_an_end():
    assert speakd.split_first_sentence("Heading line\n\nBody here.") == ("Heading line", "Body here.")


def test_no_split_without_an_end_in_range():
    text = "word " * 100
    assert speakd.split_first_sentence(text, limit=50) == (None, text)
    assert speakd.split_first_sentence("no end here") == (None, "no end here")


def test_decimal_is_not_an_end():
    assert speakd.split_first_sentence("It took 3.5 seconds. Fine.") == ("It took 3.5 seconds.", "Fine.")


@pytest.fixture
def fake_say(tmp_path, monkeypatch):
    """A `say` that records its stdin and arguments, sleeps $FAKE_SAY_SECONDS, and exits $FAKE_SAY_EXIT."""
    log = tmp_path / "say.log"
    script = tmp_path / "bin" / "say"
    script.parent.mkdir()
    script.write_text(f"""#!/bin/sh
printf '%s|' "$*" >> {log}
cat >> {log}
printf '\\n' >> {log}
sleep ${{FAKE_SAY_SECONDS:-0.2}}
exit ${{FAKE_SAY_EXIT:-0}}
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{script.parent}:{os.environ['PATH']}")
    monkeypatch.setattr(speakd, "LEVEL_FILE", tmp_path / "level")
    monkeypatch.setattr(speakd, "SAY_KIND_FILE", tmp_path / "kind")
    return log


def wait_until(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_sayproc_passes_text_on_stdin_and_voice(fake_say, monkeypatch):
    monkeypatch.setattr(speakd, "SAY_VOICE", "Samantha")
    monkeypatch.setattr(speakd, "SAY_RATE", "210")
    p = speakd.SayProc("-v dangerous text")
    assert p.wait()
    assert not p.failed()
    assert fake_say.read_text() == "-v Samantha -r 210|-v dangerous text\n"


def test_sayproc_failure_and_missing_binary(fake_say, monkeypatch):
    monkeypatch.setenv("FAKE_SAY_EXIT", "1")
    p = speakd.SayProc("hi")
    p.wait()
    assert p.failed()
    monkeypatch.setenv("PATH", "/nonexistent")
    assert speakd.SayProc("hi").failed()


def test_sayproc_kill_is_not_a_failure(fake_say, monkeypatch):
    monkeypatch.setenv("FAKE_SAY_SECONDS", "5")
    p = speakd.SayProc("hi")
    p.kill()
    assert wait_until(lambda: not p.running())
    assert not p.failed()


class StubKokoro(speakd.Speaker):
    """Speaker without a model: records which texts Kokoro was asked for, and when its first audio could be queued."""

    def __init__(self):
        self.lock, self.run_lock, self.close_lock = speakd.threading.Lock(), speakd.threading.Lock(), speakd.threading.Lock()
        self.token, self.player, self.speaking, self.listener, self.paused, self.sayproc = 0, None, False, None, False, None
        self.asked = []

    def _chunks(self, text):
        self.asked.append(text)
        yield [0.0] * 10, None, None


def tier(speaker, text):
    with speaker.lock:
        token = speaker.token
    return speaker._first_sentence_tier(text, token)


def test_tier_off_hands_everything_to_kokoro(fake_say, monkeypatch):
    monkeypatch.setattr(speakd, "FIRST_SENTENCE", "off")
    s = StubKokoro()
    list(tier(s, "One. Two."))
    assert s.asked == ["One. Two."] and not fake_say.exists()


def test_tier_say_speaks_first_sentence_once_and_kokoro_the_rest(fake_say, monkeypatch):
    monkeypatch.setattr(speakd, "FIRST_SENTENCE", "say")
    s = StubKokoro()
    t = time.time()
    chunks = tier(s, "One. Two. Three.")
    assert time.time() - t >= 0.15            # Kokoro's audio is released only after say has exited: no overlap
    assert len(list(chunks)) == 1
    assert s.asked == ["Two. Three."]         # never the first sentence again
    assert fake_say.read_text().count("One.") == 1 and "Two" not in fake_say.read_text()


def test_tier_single_sentence_needs_no_kokoro(fake_say, monkeypatch):
    monkeypatch.setattr(speakd, "FIRST_SENTENCE", "say")
    s = StubKokoro()
    assert tier(s, "Just this.") is None and s.asked == []


def test_tier_falls_back_to_kokoro_for_everything_when_say_fails(fake_say, monkeypatch):
    monkeypatch.setattr(speakd, "FIRST_SENTENCE", "say")
    monkeypatch.setenv("FAKE_SAY_EXIT", "1")
    s = StubKokoro()
    list(tier(s, "One. Two."))
    assert s.asked[-1] == "One. Two."


def test_stop_during_say_cuts_it_and_kokoro_stays_silent(fake_say, monkeypatch):
    monkeypatch.setattr(speakd, "FIRST_SENTENCE", "say")
    monkeypatch.setenv("FAKE_SAY_SECONDS", "5")
    s = StubKokoro()
    out = []
    th = speakd.threading.Thread(target=lambda: out.append(tier(s, "One. Two.")))
    th.start()
    assert wait_until(lambda: s.sayproc is not None)
    proc = s.sayproc
    s.stop()
    th.join(2)
    assert out == [None]
    assert wait_until(lambda: not proc.running())


def test_say_only_speaker_speaks_stops_and_clears_speaking(fake_say, monkeypatch):
    s = speakd.SayOnlySpeaker()
    s.say("Hello there.")
    assert s.speaking
    assert wait_until(lambda: not s.speaking)
    assert "Hello there." in fake_say.read_text()
    monkeypatch.setenv("FAKE_SAY_SECONDS", "5")
    s.say("A long one.")
    assert wait_until(lambda: s.sayproc is not None)
    proc = s.sayproc
    s.stop()
    assert not s.speaking and wait_until(lambda: not proc.running())


def test_say_only_unknown_voice_falls_back_to_system_voice(fake_say, monkeypatch):
    # the fake rejects any call that names a voice
    script = fake_say.parent / "bin" / "say"
    script.write_text(script.read_text().replace('printf', 'case "$*" in *-v*) cat >/dev/null; exit 1;; esac\nprintf', 1))
    monkeypatch.setattr(speakd, "SAY_VOICE", "Nope")
    s = speakd.SayOnlySpeaker()
    s.say("Hi.")
    assert wait_until(lambda: not s.speaking)
    assert fake_say.read_text() == "|Hi.\n"


def test_conf_file_is_read_and_the_environment_wins(tmp_path, monkeypatch):
    conf = tmp_path / "speakd.conf"
    conf.write_text('MYNAH_TTS=say-only\nMYNAH_SAY_VOICE="Samantha"\n')
    monkeypatch.setattr(speakd, "CONF_FILE", conf)
    monkeypatch.delenv("MYNAH_TTS", raising=False)
    assert speakd._conf("MYNAH_TTS", "kokoro") == "say-only"
    assert speakd._conf("MYNAH_SAY_VOICE") == "Samantha"
    monkeypatch.setenv("MYNAH_TTS", "kokoro")
    assert speakd._conf("MYNAH_TTS") == "kokoro"
