# TODO

## Subtitle matching/snapping

- Some transcribed lines appear duplicated for a short time span. We need to track if this bug is inside the snapping process or it's another type of issue. Example can be seen at jjk.ass around 02:18 (futari ni taisuru gotou satsu) although you can find other instances of this bug along the full generated file.

## Subtitle rendering

- Fix vertical positioning. Current positioning adds too much margin between each language line. Look at jjk.png for an example. Is subtitle positioning actually deterministic or it depends on client resolution or any other factor we can't control? There is also various casuistics for this: one line base sub + one line transcription, two-line base sub + one line transcription, one line base sub + two-line transcription (this one is very rare but I suppose it could happen too). And on top of that, if romanization is enabled, another layer with the similar constraints is added on top. The subtitle rendering/layout module should handle all this gracefully as much as it can.
