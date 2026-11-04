# Sun

Sun draws a breathing pixel sun above Ramabana's prompt while the agent is busy. Follow `breathe in` for four seconds and `breathe out` for six seconds. A pale-gold, nearly white core fades through amber to a soft orange halo, with eight rays. The whole sun grows from about 9 columns to 25 during the inhale, and the rays lengthen. It contracts during the exhale. Motion uses a cosine curve. Empty pixels keep the terminal's default background.

Copy this folder to `~/.config/ramabana/mods/sun/`. Start a new Ramabana session with mods enabled. Sun needs the band API in `shalya.skills.Registry` and a frontend that draws bands. Use a terminal with Unicode half-block and truecolor support.

Commands run without a model turn:

- `/sun` shows whether Sun is on and its inhale, exhale, and total duration.
- `/sun off` hides Sun.
- `/sun on` shows Sun during agent work.
- `/sun pace IN OUT` sets inhale and exhale seconds. Each value must be between 2 and 12. For example, `/sun pace 5 7` sets a twelve-second breath.

Settings last for the current mod load. Turning Sun on or changing its pace restarts the inhale. Each working spell starts its inhale when the spell began (`view.busy_since`), or at the first busy draw when the frontend does not give it. Idle draws and turn-end hooks reset the breath.

Sun uses at most seven terminal rows: six of art and the instruction, centred under the sun. The art is centred in a canvas of at most 25 columns. On a light theme (`view.theme`) the palette is deeper. On a terminal with standard colours it uses `yellow` and `bright_yellow` only, and with no colours it draws with `*`, `o` and `.`. Below 20 columns, or when fewer than three rows are available, Sun shows the instruction without art. Instructions are clipped when the terminal is narrower than the text.

Run `python preview.py --frames 5 --width 60` from this folder to print ANSI frames without a session. `--theme light` and `--colors standard` (or `256`, `none`) show the other palettes. Frames are evenly spaced from 0 to 10 seconds, including both endpoints. The preview requires Rich, which Ramabana includes. This preview uses the default four-second inhale and six-second exhale. It does not wait between frames. Use `--frames 6` to include the four-second inhale peak.
