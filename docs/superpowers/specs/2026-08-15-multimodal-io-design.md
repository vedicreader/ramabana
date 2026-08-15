# Multimodal I/O across rishi, ramabana and leela

Date: 2026-08-15

Generated images and video reaching the screen, audio reaching the model, and a
banner that says which models can do either.

## What already exists

Exploration changed the shape of this work considerably, so the starting point is
worth recording.

- **rishi already does multimodal input end to end.** `mk_oai_content`
  (`rishi/core.py:196`) sniffs bytes and emits `image_url` or `input_audio`
  content parts, and llama, litert, mlx and remote all consume them. What rishi
  has no notion of is *output* modalities, or any way to ask what a model
  supports.
- **litellm's model table already answers the capability question.**
  `fastllm.types.get_model_info('gemini-2.5-flash-image', 'gemini')` returns
  `supported_modalities: [text, image, audio, video]` and
  `supported_output_modalities: [text, image]`. Ramabana already calls that
  function in `_cloud_ctx` (`ramabana/core.py:318`) purely for the context
  window and discards the rest.
- **The table is patchy, not uniform.** `gemini-2.5-flash` reports modalities
  fully; `claude-opus-4-5` reports `None` for every modality field;
  `veo-3.0-generate-001` is absent entirely. A banner driven naively off the
  table would state that Claude accepts no images, which is false.
- **ramabana already attaches audio and deliberately refuses to send it.**
  `media_parts` (`ramabana/cli.py:279`) filters to `kind == 'image'`, and
  `media_note` tells the model "Audio is attached by path only; read it from the
  path above if you need its contents." The audio work is removing an existing
  deliberate limitation, not building a pipeline.
- **leela renders agent replies as notebook cells.** `answer_md` produces the
  cell, and `nb.py`'s cell model stores raw nbformat `outputs`, so a generated
  image is a `display_data` output the existing renderer already draws.

## The blocker, and the upstream ask

**fastllm cannot represent a generated image.** `fastllm.types.PartType` has
`input_image`, `input_audio`, `input_video` and `input_file` — every media type
is input-only. A chat-native image returned by Gemini is dropped by fastllm's
parser before rishi's `norm_completion` (`rishi/remote.py:125`) ever sees it.

`Completion.raw` does preserve the untouched provider response, so rishi can
recover the image from there. But that means rishi parsing provider-shaped
payloads — Gemini's `inline_data` against OpenAI's — which is precisely the
layering fastllm exists to remove.

**Decision:** build against `Completion.raw` now, confined to a single function
(`_gen_media`) so the provider-shaped parsing has exactly one home, and file an
upstream request with fastllm for an `output_image` `PartType`. When that lands,
`_gen_media` is replaced and nothing above it changes.

## Invocation shapes, and which repo owns which

Image and video generation come in three incompatible shapes, and they map onto
the three repos:

| Shape | Example | Reaches it via | Owner |
|---|---|---|---|
| Chat-native — images arrive inside a normal completion | `gemini-2.5-flash-image` (`mode: chat`, `supported_output_modalities: [text, image]`) | rishi's existing `Chat`, no new endpoint | **rishi** |
| Dedicated endpoint — a separate image API | `gpt-image-1` (`mode: image_generation`, only at `/v1/images/generations`) | an agent tool | **ramabana** |
| Async job — long-running, polled | `sora-2` (`mode: video_generation`), Veo | a job handle and polling | **leela** |

## Section 1 — rishi

Two additions to `nbs/00_core.ipynb`, one to `nbs/04_remote.ipynb`.

### `Caps` and `model_caps`

```python
@dataclass(frozen=True)
class Caps:
    inp:  tuple = ('text',)
    out:  tuple = ('text',)
    source: str = ''   # 'litellm' | 'mmproj' | 'runtime' | 'fallback' | 'default'

    @property
    def gen_image(self): return 'image' in self.out
```

`model_caps(model, runtime=None) -> Caps` is a pure function: it never
instantiates a `Chat`, so a picker can describe every model it lists cheaply,
including local models that would be expensive to load.

Resolution order:

1. **Cloud** — `fastllm.types.get_model_info`, reading `supported_modalities` and
   `supported_output_modalities`. `source='litellm'`.
2. **Local** — a `_caps` hook each runtime module supplies. llama already has
   `get_mmproj` (`rishi/llama.py:69`) to detect a projector beside the model;
   litert has its `multimodal` flag; mlx already routes vision repos to
   `MlxVlmChat` (`rishi/core.py:588`). `source='mmproj'` or `'runtime'`.
3. **Fallback** — a small hand-maintained table keyed by vendor prefix, for the
   providers litellm leaves blank (Anthropic). `source='fallback'`.
4. **Default** — text in, text out, `source='default'`.

The `source` field carries more weight than it appears to. It is what lets a
consumer render "unknown" instead of "no" when the table is silent, which is the
difference between an honest banner and a wrong one.

`ramabana._cloud_ctx` collapses into this — it is already making the same call
and throwing away everything but the window.

### Capture

`norm_completion` gains one call to `_gen_media(comp.raw)`, which returns
`[{'mime': str, 'data': bytes}]` and populates `res['media']`. `Resp` gains a
`.media` property.

Generated media stays off `content`, so nothing that walks response text changes
behaviour. On the following turn the existing `strip_media` / `_media_ph`
convention (`rishi/core.py:352`) replaces it with an `[image]` placeholder,
exactly as input media is already handled.

## Section 2 — ramabana

### Audio input

`media_parts` (`cli.py:279`) stops filtering to `kind == 'image'`, and
`media_note`'s "attached by path only" disclaimer becomes conditional on the
model.

The gate is `model_caps(...).inp`. A model that cannot accept audio keeps
today's path-only behaviour **and** gets a line saying why, rather than a
confusing failure at the provider. When `source == 'default'` — capabilities
unknown — audio is sent, because withholding on an unknown is how not-knowing
silently becomes a smaller agent (the same reasoning `budget_for`
(`ramabana/core.py:391`) already applies to unknown context windows).

### `generate_image` tool

A tool in `nbs/02_tools.ipynb` that calls the dedicated image endpoint, so a
Claude-driven agent can produce a picture without the user switching models. It
is registered only when the credential is present, following how the existing
optional tools gate. It saves to the session media directory and returns the
path.

### Terminal rendering

Via `kittytgp` (`render_png` / `build_render_bytes`), added as an optional
dependency. It is dependency-free, PNG-only, and kitty-protocol-only.

Its Unicode-placeholder design is what makes this tractable. teleprint's
compositor "redraws from the model on any change with absolute positioning"
(`teleprint/compositor.py:14`), so a placement made of ordinary `U+10EEEE` text
rows survives a repaint and scrolls with the transcript. A raw inline-image
escape would be wiped on the next frame. The APC transmit is written once
out-of-band through `tty.write`.

Where kitty graphics is not detected — iTerm2, Terminal.app, plain xterm — print
the saved path plus the model's own description of the image. One code path,
never corrupts a screen. kittytgp is PNG-only, so non-PNG output takes the same
path fallback rather than pulling in Pillow.

### Artifacts

Saved under the existing session directory, `leela_agent_sessions/<session>/media/`,
named `<turn>-<n>.png`. Artifacts live and die with the session record already
being kept, the path is stable enough to reference in a later turn, and the
agent can hand it to a tool. No new cleanup policy.

### Banner

`model_note` (`ramabana/core.py:371`) gains a modality summary and a distinct
marker when `Caps.gen_image` is true. It currently reads:

    gemini-2.5-flash-image · cloud · 1000k ctx

and becomes:

    gemini-2.5-flash-image · cloud · 1000k ctx · in: text image audio video · out: text image

Modalities beyond plain text are shown; a text-only model's line is unchanged.
When `source == 'default'` the line says `modalities unknown` rather than
claiming text-only.

## Section 3 — leela

Rendering is nearly free: `Resp.media` becomes a `display_data` output with
`image/png` on the reply cell, which `nb.py` already draws.

Audio input mirrors ramabana's change through the shared `leela/agent/` modules,
which alias ramabana's.

The model picker in `blocks/agent/models.py` shows the same marker as the CLI
banner.

Video is the genuinely new work: a `generate_video` tool, a persisted job handle,
polling, and an HTML5 `<video>` output in the chat cell. `veo-3.0-generate-001`
is absent from litellm's table, so this piece cannot lean on the capability layer
and needs its own hand-maintained entry.

## Error handling

- A model asked for an image that cannot produce one: the capability check
  catches it before the call and says so, naming what the model can do.
- Generated media that is not PNG: saved, path printed, not drawn. Stated, not
  silent.
- kittytgp absent, or the terminal does not speak kitty graphics: path fallback.
- `get_model_info` raising or returning nothing: `Caps` with `source='default'`,
  never an exception out of `model_caps`. `_cloud_ctx` already swallows failure
  this way.
- A video job that fails or times out: the handle persists, and the failure is
  reported with the job id so it can be re-checked.

## Testing

rishi: `model_caps` against fixture model-info dicts covering the four
resolution paths, and `_gen_media` against a recorded `raw` payload. No network,
no model load.

ramabana: pytest in `tests/`, house sentence-style names, plain `assert`, doubles
from `ramabana.testing` —

- `test_audio_is_withheld_from_a_model_that_cannot_hear_it`
- `test_audio_is_sent_when_the_model_capabilities_are_unknown`
- `test_a_terminal_without_kitty_graphics_gets_a_path_not_escape_bytes`
- `test_the_banner_says_unknown_rather_than_text_only_for_an_untabled_model`

The readable `test_eq` examples live in the notebooks, per the division set out
in `CLAUDE.md`. No test loads a model.

## Sequencing

1. rishi — `Caps`, `model_caps`, `_gen_media`. Both consumers depend on it.
2. ramabana — audio input, banner, terminal render, `generate_image`.
3. leela — chat rendering, audio, model-picker marker, video jobs.
