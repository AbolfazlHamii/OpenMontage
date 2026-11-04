# Camera snippet test workspace

The HyperFrames composition that checks every snippet in
`skills/creative/camera-language.md` (Part B). Rendered 2026-11-04 with
`npx hyperframes render --quality draft` (lint: 0 errors), 16 s, one 2 s
scene per technique; frames inspected for edges, blur and motion.

To run it again, copy this folder somewhere outside the repo, add
`assets/js/gsap.min.js` (any HyperFrames workspace has one) and generate the
test images:

```bash
mkdir -p assets/img && cd assets/img
ffmpeg -y -f lavfi -i "gradients=s=1920x1080:c0=0x1428a0:c1=0xfff8ec:x0=0:y0=0:x1=1920:y1=1080:d=1" -vf "drawgrid=w=120:h=120:t=3:c=0x000000@0.35" -frames:v 1 bg.png
ffmpeg -y -f lavfi -i "color=c=0xff8a2a@1:s=600x600,format=rgba,geq=r='255':g='138':b='42':a='if(lt(hypot(X-300,Y-300),280),255,0)'" -frames:v 1 fg.png
ffmpeg -y -f lavfi -i "color=c=black:s=1920x1080,format=gray,geq=lum='clip(255-hypot(X-960,Y-760)/4,0,255)'" -frames:v 1 depth.png
for T in 96 160 208; do ffmpeg -y -i depth.png -vf "format=gray,geq=lum='if(gte(lum(X,Y),$T),255,0)'" depth_$T.png; done
cd ../.. && npx hyperframes render --quality draft --output snippets.mp4
```
