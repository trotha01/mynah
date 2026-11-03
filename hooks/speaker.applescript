-- Starts mynah's resident speaker (src/mynah/speakd.py) in the user's desktop (Aqua) session.
-- Compiled into "Mynah Speaker.app" by hooks/build-speaker-app; hooks/claude-speak runs it with `open -g`.
-- A process started by a hook belongs to the tmux server's Background session, where macOS never reports the
-- push-to-talk key; an app started through LaunchServices, and the speaker it starts, belong to the desktop session.
do shell script "cd /tmp && HF_HUB_OFFLINE=1 PATH=/opt/homebrew/bin:$PATH nohup \"$HOME/.local/share/uv/tools/mynah/bin/python\" -m mynah.speakd >>\"$HOME/Library/Logs/mynah-speakd.log\" 2>&1 </dev/null &"
