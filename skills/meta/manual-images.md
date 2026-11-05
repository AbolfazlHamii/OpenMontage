# Manual images (the owner makes the stills)

Use when the owner wants to generate the stills of a still-led video
themselves in Nano Banana (Gemini app or AI Studio, often free or cheaper
than the API) while the pipeline does everything else: narration, timing,
camera moves, captions, stamps, music and the render.
Code: `lib/fa_manual_images.py`, CLI `scripts/fa_manual_images.py`.

## Flow

1. **Script first.** The narration is approved as usual (script director,
   `skills/creative/narration-craft.md`, `scripts/fa_script_lint.py`).
2. **Shot list (agent).** `init --project projects/<id>` writes
   `manual_images/shotlist.json`; fill it from the script:
   - one scene per narration beat: `narration` (spoken, numbers as words),
     `caption` (digits), optional `stamp` (era/place, HTML, never in the
     image), `transition` (`cut` or `flash` for a time jump), optional
     `audio` (an existing clip instead of TTS);
   - shots per scene: `id` (the file name the owner saves), `prompt`
     (English, what the image shows; follow `camera-language.md` Part A and
     the channel's look), `camera` (`push_in`, `pull_out`, `pan_left`,
     `pan_right`, `tilt_up`, `tilt_down`, `still`; leave it out and the
     builder varies it), `focus` ([x, y] 0..1, the point the move centres
     on), `weight` (share of the scene's time);
   - `style.prompt` (appended to every prompt), `style.references`
     (style/character images the owner attaches for consistency),
     `voice` (`channel`, optional `voice_id`, `style`, `providers`),
     `music` (`path`, `volume`).
   Aim for the edit card's shot length (e.g. ~3.3–3.8 s for "the entire
   history of X"): a 90 s video is ~25 shots.
3. **Prompt pack.** `prompts` writes `manual_images/PROMPTS.md` and
   `manual_images/prompts.html` (copy buttons, previews of saved images,
   Persian instructions). Give the owner the HTML path.
4. **Owner makes the images** and saves each as `manual_images/in/<shot id>.png`
   (jpg/webp also work). Rules in every prompt: no text or logos, 16:9,
   subject in the upper two thirds.
   **ZAPI FLOW (bulk, Google Flow).** `prompts` also writes
   `manual_images/zapi_flow.txt` (one full prompt per line, in shot order)
   and `zapi_flow_order.json` (row → shot id); the HTML page has a "copy all"
   box. The owner pastes it into the ZAPI FLOW extension, sets Flow to image
   mode and landscape 16:9, and turns on "serial number in filename". Then
   `import --project projects/<id> --from <download folder>` copies each row
   to `in/<shot id>.<ext>`: by the first number in the file name when every
   file has one in range, else in download order (`--by serial|time` to
   force). Extra outputs of the same row go to `in/alts/`; images already in
   `in/` are kept unless `--overwrite`. Report: `manual_images/flow_import.json`.
   ZAPI FLOW cannot attach reference images, so recurring people go in
   `style.characters` (`{"Lenin": "bald man, pointed beard, ..."}`) and each
   shot lists who appears (`"characters": ["Lenin"]`); the same description
   is then written into every prompt that shows them.
5. **Check.** `check` lists missing, unreadable, non-16:9 (cropped by the
   camera) and small (< 1280 px) images. Look at the images too: text in
   an image, wrong era, a character that changed face — ask for a redo.
6. **Build.** `build --render`: narration per scene through `tts_selector`
   with the channel lexicon (clips cached by text and voice, so editing one
   scene re-voices only that scene), timing from the clip lengths (0.25 s
   lead-in, 0.35 s breath after each line, shots split by weight with a
   1.2 s floor), captions split at clause marks into lines of ≤ 6 words that
   never end on a preposition or an ezafe, a HyperFrames workspace in
   `manual_images/workspace/`, render, −14 LUFS / −1.5 dBTP. The result
   reports each scene's pace (letters/s; ~9–10 is normal).
7. **Review** the render like any other (`scripts/fa_render_qa.py`, the
   edit pass in `skills/creative/editing-craft.md` for SFX and word-timed
   captions).

## Notes

- Captions are timed by letter share of the line, not by word timestamps.
  For word-exact captions, run the edit pass on the workspace.
- Demo (2026-11-05): `projects/_manual_demo/` with the three Samsung
  sample stills standing in for the owner's images: 14.8 s, 7 caption
  lines, −14.03 LUFS, narration $0.003.
