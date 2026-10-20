# Showreel

Source of `assets/showreel.mp4` and `assets/showreel.gif`, the 30 second motion graphics clip on the project page.

`index.html` draws every frame from one function, `render(t)`, so the video is the same on every run. `render.mjs` opens it in
Chrome, takes 30 frames per second and writes them as PNG files. To change the pace, edit `SLOW` (how much slower than
written the animations play) and `HOLD` (seconds each scene stays on screen once it is done) at the top of the script.
Fonts are Geist Mono (SIL Open Font License, see `fonts/`).

The soundtrack is a slow dub techno groove that `music.py` synthesises from scratch (Fm9 and Dbmaj9 chord stabs through a
dark ping-pong delay and reverb, over a deep kick and sub bass), so it is as free to use as the rest of the project and is rebuilt the same way.

```shell
npm i puppeteer-core ffmpeg-static
uv run --with numpy --with scipy python music.py music.wav 30
CHROME="/path/to/chrome" node render.mjs frames
"$(node -p 'require("ffmpeg-static")')" -framerate 30 -i frames/f%04d.png -i music.wav \
  -c:v libx264 -crf 17 -pix_fmt yuv420p -af loudnorm=I=-16:TP=-1.5 -c:a aac -b:a 192k -movflags +faststart ../../assets/showreel.mp4
```

The GIF is the same frames without sound at 15 fps and 960 pixels wide, with a 128 colour palette (`palettegen`, then
`paletteuse=dither=bayer:bayer_scale=5`, which keeps the gradients smooth without noise on the flat background).
