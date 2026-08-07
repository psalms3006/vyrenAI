# VYREN voice-silence fix — what changed and why

## Root causes found (2, independent)

1. `voice/runtime.py` wrapped both the `google.genai` import and the
   `voice_engine` import in bare `except Exception:` with NO logging.
   Any failure in either — missing package, wrong venv, a real bug —
   produced the exact same message ("Gemini Live unavailable — falling
   back to offline voice") with zero diagnostic trail. Confirmed by
   reproducing the failure locally with the SDK absent, then again with
   it installed (imports cleanly) — the engine code itself is not the
   problem; the silent except was hiding whichever problem it was.

2. `_start_fallback()` in `voice/runtime.py` checked for `sounddevice`
   BEFORE calling `self._notify_state("fallback")`. That notify is the
   only thing that moves `InteractionController` out of its default
   "silent" mode (see `interaction/interaction_controller.py` and
   `interaction/mode_manager.py`, `_active_mode` defaults to
   `USER_MODES["silent"]`). When sounddevice was missing, the function
   returned before ever notifying — so the assistant spoke once (via a
   separate boot-time greeting watchdog that bypasses interaction mode
   entirely) and then every subsequent turn was gated by
   `may_speak() == False`, producing:
   "[VYREN is quiet — enable conversation mode or use wake word]"

## Files changed

### voice/runtime.py
- `google.genai` import except-block now logs the real exception
  (`exc_info=True`) instead of swallowing it silently.
- `voice_engine` import except-block: same fix.
- `_start_fallback()`: moved `self._notify_state("fallback")` to run
  immediately, before the sounddevice check — so InteractionController
  always leaves "silent" mode even when the offline loop can't fully
  start.

### runtime/manager.py
- `_greeting_watchdog()`: now also calls
  `interaction_controller.set_user_mode("conversation")` before firing
  the greeting, as a second safety net for the same failure mode (in
  case voice never reaches a state that would normally trigger this).

## What this does NOT fix (needs to happen on your machine, not in code)

- `google-genai` was confirmed NOT installed anywhere you checked.
- Your shell's `pip`/`python` currently resolve to
  `C:\Users\Lenovo\AppData\Local\Hermes\hermes-agent\venv\...`, not
  `C:\Users\Lenovo\my-project\.venv`. sounddevice/pyttsx3 just installed
  into the WRONG venv (Hermes' agent venv). Verify which interpreter
  actually runs `python main.py` and install into that one:

    .\.venv\Scripts\python.exe -m pip install google-genai sounddevice pyttsx3

## What to tell the other agent (Hermes)

The InteractionController / ModeManager / ConversationStateMachine
system it added (`interaction/`) is architecturally fine — the bug is
that its ONLY exit path out of the default "silent" mode is a single
`set_user_mode("conversation")` call gated behind a voice-state
callback that has failure paths which never fire it. That's a
single-point-of-failure design: any new voice failure mode added in the
future needs to remember to also unblock interaction mode, or the
symptom returns. Worth considering: default to a mode other than
"silent", or have `may_speak()` fail open after a boot grace period
instead of failing closed forever.

---

## Round 2 (after real logs came back — this is what unmasking the silent except actually found)

### voice/runtime.py — `_build_live_config()`
Last line was:
    cfg = types.LiveConnectConfig(**live_kwargs)
    return cfg.model_dump_json(exclude_none=True)   # <-- returns a JSON STRING

Fixed to:
    cfg = types.LiveConnectConfig(**live_kwargs)
    return cfg

This is THE bug that caused every single Gemini Live connect attempt to
fail with `'str' object has no attribute 'tools'`. The callback is
supposed to return a LiveConnectConfig object; engine.py immediately
does `config.tools` on whatever it gets back. Returning the serialized
JSON string instead of the object itself guarantees failure on every
attempt, which matches the boot log 1:1 (4 attempts, all identical
error, then give-up-and-fallback).

### voice_engine/engine.py — `_run_session()`
Removed a duplicate `config = self._build_session_config()` call (was
calling the config builder twice per connection attempt — matches the
"Building LiveConnectConfig" line appearing twice per attempt in the
log). Not the cause of the crash, but redundant and worth cutting since
the callback rebuilds system prompt/memory context fresh each call.

## What to tell Hermes about this one specifically

`model_dump_json()` vs returning the object directly is an easy typo to
introduce if the same function was ever used for BOTH logging (where
you'd want the JSON string) and building the actual session config
(where you need the live object) and got merged/copy-pasted. Worth
grep'ing for any other `.model_dump_json(` calls near config-building
code as a general sanity check — this exact class of bug (serialize
instead of return) is easy to reintroduce in the same file/pattern.

---

## Round 3 — text input still gated after voice worked

### interaction/interaction_controller.py
`on_wake_word_detected()`, `on_user_input()`, `on_user_activity()` all
attempted a direct `transition(ACTIVE_CONVERSATION)`. This is illegal
from the controller's boot state, BACKGROUND (see
interaction/conversation_state.py's VALID_TRANSITIONS — BACKGROUND only
permits PASSIVE_LISTENING, SLEEP, OFF). Nothing anywhere in the repo
ever transitions this state machine through PASSIVE_LISTENING first, so
every wake attempt was silently rejected and the state stayed BACKGROUND
forever. may_speak()'s first check, is_quiet(), is True for BACKGROUND
— so it returned False unconditionally, before user mode was even
consulted. This is why setting mode to "conversation" (round 1's fix)
never actually solved the "[VYREN is quiet]" text-path symptom.

Voice never hit this because the raw Gemini Live audio path doesn't
call may_speak() at all — only terminal.py's typed-input path does.
That's also the direct answer to "why does voice work but text
doesn't": they're genuinely two different code paths, and only one of
them ever checked permission.

Fix: added `_wake_to_active_conversation()`, which tries the direct
jump first and, if illegal, walks BACKGROUND -> PASSIVE_LISTENING ->
AWAITING_WAKE_WORD -> ACTIVE_CONVERSATION. All three wake entry points
now go through it. Verified with a direct simulation of the boot
sequence: before the fix, may_speak() was False even with mode set to
"conversation"; after, state correctly lands on ACTIVE_CONVERSATION and
may_speak() returns True.

## What to tell Hermes about this one

Same root shape as round 2's bug: a value/state silently discarded
because two independent systems (mode vs. state machine) both gate the
same decision and only one was ever wired to actually change. Also
worth flagging: on_speak_done() has the same direct-jump-to-
ACTIVE_CONVERSATION pattern from SPEAKING, which per VALID_TRANSITIONS
is ALSO not legal (SPEAKING only permits THINKING, INTERRUPTED, SLEEP,
OFF) — only legal from THINKING. Not yet confirmed as live-broken (post-
speak behavior wasn't reproduced in the logs I traced), but same shape,
worth a look before it produces a fourth version of this exact bug.

---

## Round 4 — "make it feel natural" (studied Mark-XXXIX-OR, only took one thing)

Compared VYREN against github.com/FatihMakes/Mark-XXXIX-OR directly,
line by line, on everything that affects conversational feel:

- VAD/turn-taking tuning: Mark-XXXIX-OR sets none (raw Gemini defaults).
  VYREN already has explicit tuned sensitivity/padding/silence config.
  VYREN is ahead here — did not change it.
- Mic-drop-during-playback: identical mechanism in both. No difference.
- Tool declarations sent to the voice session: Mark-XXXIX-OR sends all
  of them; VYREN deliberately sends a curated 6-tool subset because the
  full set previously caused real 1007 config-size errors. VYREN is
  ahead here — did not change it.
- System prompt conversational economy: Mark-XXXIX-OR's prompt has
  explicit tight rules (1-2 sentences max, never narrate "I'm doing X"
  before a tool call, don't repeat yourself, stay silent after slow
  tool results). VYREN's voice session was reusing the full text-mode
  identity/philosophy prompt with no equivalent — this is the one real
  gap, and plausibly part of what read as "not effortless," possibly
  also a contributor to the earlier 17s thinking delay (longer persona
  content nudges toward longer, more deliberated responses).

### voice/runtime.py — `_build_system_prompt()`
Added a "Voice Conversation Rules" block (voice-only, does not touch
system_prompt.py or the shared text-mode prompt) directly adapted from
Mark-XXXIX-OR's brevity rules. Placed early in the assembled prompt so
it survives the existing 5000-char truncation even if memory/world-model
context gets cut from the tail.

No protocol, state-machine, or config code touched this round — every
other component compared favorably to the reference repo, so there was
no reason to risk a fifth regression by importing architecture that's
already behind what's here.

---

## Round 5 — real log with 4 new findings after "make it feel alive"

### voice_engine/engine.py — recurring 1007 "invalid frame payload data"
Mic audio was sent with `mime_type: "audio/pcm"` — no sample rate
parameter — while the actual capture stream runs at
`self._config.send_sample_rate` (16000 Hz). Gemini Live's realtime
audio input expects the rate embedded in the MIME string
(`audio/pcm;rate=16000`); without it the server has to guess the
format, and "invalid frame payload data" is the error class you get
when that guess is wrong. This matches the observed pattern exactly:
fails right as real audio starts flowing, self-heals on reconnect
(server-side guess is timing/state dependent), recurs on the next
real audio burst. Also the most likely contributor to the ~2m21s-idle
1006 abnormal-closure seen in the same log — if every frame (including
continuous silence-level audio sent during idle) carried the same
malformed mime_type, accumulated invalid frames could plausibly
destabilize the session over time, not just at turn start. Fixed to
`f"audio/pcm;rate={self._config.send_sample_rate}"`.

### event_bus.py — shutdown AttributeError
`EventBus.clear_subscribers()` was called from two places
(`runtime/manager.py`, `core/__init__.py`) but never existed on the
class — every shutdown logged `'EventBus' object has no attribute
'clear_subscribers'` and skipped cleanup. Added the method for real,
clearing `self._subscribers` under the existing lock.

### Not fixed, flagged only
- `[Errno 11001] getaddrinfo failed` during the same session — Windows
  DNS resolution failure, environmental (network blip), not app code.
  Reconnect backoff (3.0s/4.5s/6.8s) behaved correctly; it just ran out
  before the network came back.
- `thinking_config` is in voice/runtime.py's allowed live-config keys
  but never actually assigned a value in `_build_live_config()` — so
  the model runs Gemini's server-side default thinking level. Not
  changed yet; worth tuning only after confirming whether latency is
  still a problem post-fix, since there's no direct evidence yet that
  this specific default is the cause.

---

## Round 6 — 1007 persisted after mime_type fix; two more real things found

The mime_type fix from round 5 was correct and worth keeping, but the
log proved it wasn't the (only) cause — 1007 recurred at the exact
same point: right after connect, before any real user speech.

### Real, confirmed bug (independent of 1007, fixed regardless)
brain/greetings.py and brain/greeting_engine.py had 5 `open()` calls
with no explicit encoding — on Windows that silently uses the system
codepage (commonly cp1252), not UTF-8. Any non-ASCII character
(em-dashes, curly quotes, etc.) written to or read from the greeting
history/bank files through this path can get genuinely corrupted, not
just mis-displayed. Fixed all 5 to `encoding="utf-8"`.

### Live hypothesis, not yet confirmed — instrumented instead of guessing again
Your log showed the boot greeting text rendered as mojibake in the
console (`â€"` instead of `—`). WebSocket close code 1007 is, per RFC
6455, specifically defined as "received data that isn't valid UTF-8" —
which makes garbled greeting text a strong candidate. But garbled
*console output* on Windows PowerShell is very often just a display
artifact of the terminal's codepage, not proof the actual in-memory
string (and therefore the actual API payload) is corrupted. I don't
have enough evidence yet to say the greeting text is the cause rather
than the mic audio stream — both happen in the same 2-4 second window
after connect.

### voice_engine/engine.py — `send_text()`
Added a diagnostic: before every send_client_content call (this is
what the greeting/typed-text path uses), it now encodes the outgoing
text as strict UTF-8 and logs either "clean UTF-8" or, if it fails,
logs the exact error and a repr() of the bad text. Also stopped
swallowing exceptions from send_client_content itself — now logged
with a full traceback instead of just diag.log_error.

## What this gets you next run
If 1007 recurs, the log will now show ONE of two things definitively:
1. "[SEND_TEXT] text is NOT clean UTF-8" right before the crash → the
   greeting/text path is confirmed as the cause, fix becomes sanitizing
   greeting text before send.
2. No such log line, 1007 still happens → it's the raw mic audio
   stream, not text, and the next thing to instrument is per-chunk
   audio validation in the sender worker.
Either way, the next log stops this from being a third guess.

---

## Round 7 — real log finally gave conclusive evidence, not another guess

### Text-encoding hypothesis: DEAD, confirmed by the diagnostic itself
The round-6 UTF-8 diagnostic in send_text() never once logged a "NOT
clean UTF-8" error across two greetings and a typed message, all
followed by 1007. That check is ERROR-level, not filtered — its
silence is real evidence. Text content is not, and was never, the
cause of 1007. Ruling this out for good.

### tools/screen_tools.py — real bug, trivial fix
`capture_and_analyze` (and capture_screen) call `datetime.now()` but
the file never imports datetime. Every single camera/vision voice-tool
call was failing with `NameError: name 'datetime' is not defined`, every
time, 100% reproducible. Added `from datetime import datetime`.

### voice_engine/protocol.py — the actual biggest finding this round
`barge_in_enabled` defaulted to True: full-duplex, mic stays hot and
streams to Gemini even while VYREN is speaking through the speakers,
gated only by a loudness threshold — with no real acoustic echo
cancellation. On a real mic+speaker setup (not headphones), VYREN's own
voice clears that threshold easily. Confirmed happening: your first
real turn transcribed as "あ、かにしゃみの" — garbage, and two turns
later VYREN "heard" its own previous reply back as new user input
("User: Yes. I can hear you clearly. How can I help you?" — that's
VYREN's own prior line). Changed the default to False: mic mutes while
VYREN talks, same approach Mark-XXXIX-OR uses. Trades away true
mid-sentence interruption for a conversation that doesn't confuse
itself with its own voice. This is very likely the largest single
contributor to "doesn't feel like a normal conversation," independent
of the 1007 issue.

### On "copy NOVA's voice pipeline"
I don't have NOVA's actual source in this session — only summarized
notes from past conversations, not code I can diff or port from
directly. If there's a specific mechanism in NOVA's pipeline you want
matched exactly (not just "make it feel like it did"), share that
file and I'll compare it line-for-line the same way I did with
Mark-XXXIX-OR, rather than guess at what it does from memory.

## What's still open, honestly
1007 itself is not yet root-caused. Ruled out: text encoding. Not yet
ruled out: raw PCM frame corruption unrelated to the echo issue (e.g.
chunk alignment, byte length). The echo fix may reduce or eliminate
apparent 1007 frequency as a side effect if some of those frames were
also malformed self-echo audio — that's testable in the next run, not
yet proven.

---

## Round 8 — text input had no fallback path at all

This run's boot log was the same wrong-interpreter issue as before
(bare `python`, not the venv — `No module named 'google.genai'` /
`No module named 'numpy'` again). Not a regression, same environment
mistake. But it surfaced a real, separate, worth-fixing bug: typed
text has ALWAYS only worked when Gemini Live is the active engine.
`send_text()` in voice/runtime.py had no else branch — if the engine
wasn't active (any fallback state, for any reason, tonight or in
the future), typed text silently went nowhere. No error, no reply,
nothing.

### voice/offline_loop.py
Extracted the shared reasoning+speak logic out of `_handle_utterance`
into `_process_reasoning_turn()`, and added a new public method
`handle_text()` that feeds typed text straight into that same
pipeline, skipping transcription entirely.

### voice/runtime.py — `send_text()`
Now falls through to `self._offline_loop.handle_text()` when the
Gemini Live engine isn't active. If literally neither is available, it
now logs a real warning with the current voice mode instead of doing
nothing silently — so a text-input dead end is visible in the log
going forward instead of invisible.

## Reminder for next run
Use `.\.venv\Scripts\python.exe main.py`, or run
`.\.venv\Scripts\Activate.ps1` once per terminal session first. Every
"Gemini Live unavailable" / "numpy not found" log so far has traced
back to this, not to any of the code fixed in rounds 1-8.

---

## Round 9 — the actual 1007 root cause, correcting an earlier mistake

Four 1007 events in one log, checked against timing: every single one
landed within ~1 second of a send_client_content call (the boot
greeting once, "hi" twice, "im tired" once). Zero exceptions across
four data points. That is the trigger, not audio.

### I was wrong earlier, correcting it directly
When Hermes flagged "send_client_content vs send_realtime_input" as an
undocumented deviation, I said reverting it would break typed-text
input because "you can't send text through send_realtime_input."
Checked the actual installed google-genai SDK just now:
`send_realtime_input()` has a native `text=` parameter. That claim was
wrong. Hermes had the right instinct on this one.

The actual SDK docstring for send_client_content states directly:
"Interleaving send_client_content and send_realtime_input in the same
conversation is not recommended and can lead to unexpected results."
VYREN does exactly that — continuous mic audio via send_realtime_input
in the sender worker, greeting/typed text via send_client_content
concurrently in the same session. That's the real mechanism behind
every 1007 seen across this entire session.

### voice_engine/engine.py — send_text()
Changed from:
    await self._session.send_client_content(
        turns={"parts": [{"text": text}]}, turn_complete=True)
to:
    await self._session.send_realtime_input(text=text)
Stays in the same channel as the continuous audio stream instead of
interleaving a second, documented-as-risky API. This should also
directly fix "mic turns off and restarts" (that's the reconnect cycle
1007 was triggering) and "text isn't working" (typed text was reaching
the engine fine, per the terminal log, but immediately killing the
session before a reply could come back).

## Not yet explained
The failed camera/zoom-in turn in this log didn't show a [TOOL]
Received line at all — the model didn't attempt to call
capture_and_analyze this time, unlike the earlier datetime-NameError
case where it did call it and crashed. Likely a transcription/intent
issue (the logged user text was garbled: "Can you Can you zoom out the
move into my camera?"), not a code bug I can fix blind. Worth watching
once the connection is actually stable enough to test camera requests
cleanly.

---

## Round 10 — voice attempt #2, and the real Pillow bug

Confirmed from round 9's log: zero 1007 errors across a full multi-turn
session. That fix holds.

### voice_engine/engine.py — "doesn't hear me when I talk, only when I text"
Hypothesis, not proven — I don't have a live API to test against.
Mechanism: send_realtime_input(text=...) shares the same channel as
continuous mic audio. If a text send (including the automatic boot
greeting, which fires before you ever get a chance to speak) doesn't
cleanly close out the audio stream, it could leave server-side
automatic activity detection in an ambiguous state for whatever speech
comes next. Checked: automatic_activity_detection is properly enabled
(disabled=False), so that's not off outright. Added
`send_realtime_input(audio_stream_end=True)` immediately before every
text send, to explicitly close the audio stream rather than leave it
ambiguous. This needs your next log to confirm or rule out — if voice
still doesn't respond after this, this hypothesis is wrong and the
next thing to check is whether mic audio is actually reaching the
sender queue at all during real speech (would need a per-chunk debug
log, not added yet since it's noisy).

### tools/screen_tools.py — the real Pillow bug, confirmed
Same bug class as the earlier datetime issue, in the same file:
`_capture_screen()` does `from PIL import ImageGrab` (succeeds, Pillow
IS installed) then immediately `os.makedirs(...)` — but `os` was never
imported in this file. NameError, caught by the generic
`except Exception: return ""`, silently swallowed, and the caller
always shows the hardcoded "you need Pillow" message regardless of
what actually broke. `capture_and_analyze()` also directly uses
`os.environ.get(...)` later in the same function — same missing
import affects it too.

Fixed: added `import os`. Also changed `_capture_screen` to return
`"ERROR:<real exception>"` instead of a bare empty string on the
generic except branch, and updated both call sites
(capture_screen, capture_and_analyze) to only show the "install
Pillow" message when the library is actually missing — any other
failure now surfaces the real error text instead of a misleading one.
This should prevent a third instance of "wrong error message hides
real bug" in this file going forward.

---

## Round 11 — four confirmed bugs from one dense log

Real evidence this time, not another single guess: 'User: "Can you mean
now?"' at 12:16:04 — a genuine spoken-audio transcript — happened right
after a reconnect, before any text was sent. Round 10's audio-boundary
fix is working, at least right after a fresh connection. It appears to
degrade again once text gets sent mid-session, which pointed at a real
race rather than just a missing signal.

### tools/screen_tools.py, tools/vision_tools.py — Part.from_text TypeError
`types.Part.from_text(question)` — positional. Checked the installed
SDK: `Part.from_text` is keyword-only (`*, text: str`). Every
analyze_image call was failing with this TypeError regardless of
Pillow/mss being installed. Fixed both call sites to
`Part.from_text(text=question)`.

### voice/runtime.py — the accumulating repeated-text bug
`get_last_assistant_reply()` didn't return the last reply — it joined
EVERY model-role turn in `recent_turns`, reversed, into one string.
That's exactly why printed replies kept growing every turn and
appeared in reverse-chronological order (newest first, then
progressively older text stacked behind). `self._last_reply` was
already being correctly maintained per-turn and just wasn't being
used. Fixed to return it directly. This was a display bug only — the
actual audio VYREN spoke each turn was the correct, short, per-turn
reply (visible in the [TURN] Complete log lines); only the terminal
print was broken.

### voice_engine/conversation_manager.py — SPEAKING -> THINKING
Confirmed recurring across many turns: "[CONV] Rejected transition
speaking -> thinking" fired every time the model called a second tool
while still finishing a prior turn — a completely normal pattern
(analyze_image retried 4x with different extensions in one exchange).
SPEAKING was the one state in the table that couldn't reach THINKING
directly, inconsistent with every other active-conversation state.
Added it.

### voice_engine/engine.py — send/audio race, proper fix this time
Round 10 added an audio_stream_end signal before text sends, which
helped (confirmed by the real transcript above) but wasn't sufficient
alone — a signal doesn't prevent an audio chunk from _worker_sender
landing on the wire concurrently with a text send, since nothing
previously serialized the two. Added `self._send_lock` (asyncio.Lock,
recreated fresh per session alongside the mic/speaker queues) and wrapped
both the audio send in _worker_sender and the text send in send_text()
in it. They literally cannot interleave at the send() call now, not
just "shouldn't in practice."

## Still open
Whether the lock fully fixes "doesn't hear me after I've typed once"
needs your next log — this is a stronger fix than round 10's alone,
but I don't have a live API to confirm it eliminates the pattern
rather than just reducing it.

---

## Round 12 — confirmed fix, confirmed still-broken, diagnostics not another guess

### Confirmed by this log
- The repeated/accumulating text bug is gone. Every VYREN reply printed
  clean and once. Round 11's fix holds.
- Voice still doesn't hear you. Every User: field is still empty, and
  you confirmed it directly. Round 10 (stream-end signal) and round 11
  (send lock) did not fix this. Not claiming otherwise.

### voice_engine/engine.py — diagnostics only, no architecture change
Per the explicit instruction to stop redesigning the voice pipeline: no
guess this round. The engine already tracks mic_frames_sent and
mic_frames_dropped correctly (voice_engine/diagnostics.py), they were
just never surfaced anywhere in the logs. Added one throttled log line
(~every 10s) in the existing supervisor loop:
  [MIC_DIAG] frames_sent=N frames_dropped=N seconds_since_last_frame=X
Next real conversation attempt will show definitively whether mic
audio is actually reaching the send point while you're speaking, or
whether it's stalled despite the stream being "open". That distinction
determines whether the next real fix is in the mic capture path or
somewhere in how Gemini processes what it receives — currently unknown
which one it is.

### Not touched, and not chased this round
1008 "policy violation" and 1006 "abnormal closure" during multi-minute
idle gaps — present in this log, but also present in logs from many
rounds ago, before recent changes. Not a new regression, so per this
round's explicit priority, not investigated further right now.

### On "it can still be speaking whilst thinking/calling tools, just do
it intellectually" — this is already how it behaves as of round 11's
SPEAKING -> THINKING fix in conversation_manager.py. No further change
needed there unless it's observed behaving badly in practice.
