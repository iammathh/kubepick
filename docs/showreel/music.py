# Soundtrack of the showreel: a slow dub techno groove, synthesised from scratch so it can be rebuilt and is free to use.
# python music.py music.wav [seconds]
import sys

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfilt

RATE = 44100
BPM = 120
BEAT = 60 / BPM
BAR = 4 * BEAT
STEP = BEAT / 4
rng = np.random.default_rng(7)

def times(seconds):
	return np.arange(int(seconds * RATE)) / RATE

def hz(midi):
	return 440 * 2 ** ((midi - 69) / 12)

def lowpass(x, cutoff, order=2):
	return sosfilt(butter(order, cutoff, "low", fs=RATE, output="sos"), x)

def highpass(x, cutoff, order=2):
	return sosfilt(butter(order, cutoff, "high", fs=RATE, output="sos"), x)

# Add a sound into a track at a time in seconds, cutting it off at the end of the track
def place(track, sound, at):
	start = int(at * RATE)
	length = min(len(sound), len(track) - start)
	if length > 0:
		track[start:start + length] += sound[:length]


### Instruments ###

def kick():
	t = times(0.5)
	pitch = 44 + 80 * np.exp(-t * 30)
	body = np.sin(2 * np.pi * np.cumsum(pitch) / RATE) * np.exp(-t * 6.5)
	click = lowpass(rng.standard_normal(len(t)), 3000) * np.exp(-t * 400) * 0.08
	return body + click

def hat():
	t = times(0.08)
	return highpass(rng.standard_normal(len(t)), 7500) * np.exp(-t * 70)

def saw(frequency, t):
	return 2 * ((frequency * t) % 1) - 1

# The dub techno chord stab: detuned saws through a low-pass filter whose cutoff moves over the whole piece
def stab(notes, cutoff):
	t = times(0.4)
	tone = sum(saw(hz(n) * d, t) for n in notes for d in (0.996, 1.004)) / (2 * len(notes))
	envelope = np.minimum(t / 0.004, 1) * np.exp(-t * 11)
	return lowpass(tone * envelope, cutoff, order=4)

def pad(notes, seconds):
	t = times(seconds)
	tone = sum(np.sin(2 * np.pi * hz(n) * d * t) for n in notes for d in (0.997, 1.003)) / (2 * len(notes))
	swell = np.sin(np.pi * np.clip(t / seconds, 0, 1)) ** 1.5
	return lowpass(tone * swell, 900)

def bass(note, seconds):
	t = times(seconds)
	tone = np.tanh(1.6 * np.sin(2 * np.pi * hz(note) * t))
	return tone * np.minimum(t / 0.03, 1) * np.exp(-t * 2.5)

# Feedback delay with every repeat darker than the last, bouncing between the left and the right
def dub_delay(x, time, feedback, repeats=9):
	left, right = np.zeros_like(x), np.zeros_like(x)
	echo = x
	for k in range(1, repeats + 1):
		echo = lowpass(echo, 2200) * feedback
		shift = int(k * time * RATE)
		target = left if k % 2 else right
		target[shift:] += echo[:len(x) - shift]
	return left, right

def reverb(x, seconds=3.2):
	t = times(seconds)
	out = []
	for _ in range(2):
		impulse = lowpass(rng.standard_normal(len(t)), 3500) * np.exp(-t * 2.0)
		out.append(fftconvolve(x, impulse / np.sqrt(np.sum(impulse ** 2)))[:len(x)])
	return out


### Arrangement ###

# Fm9 and Dbmaj9, four bars each
CHORDS = [([53, 56, 60, 63, 67], 41), ([49, 53, 56, 60, 63], 37)]
STAB_STEPS = [3, 10]

def song(seconds):
	n = int(seconds * RATE)
	t = times(seconds)
	drums, stabs, pads, bassline, hats = (np.zeros(n) for _ in range(5))
	bars = int(np.ceil(seconds / BAR))
	last_bar = int(seconds // BAR) - 1

	for bar in range(bars):
		start = bar * BAR
		notes, root = CHORDS[(bar // 4) % len(CHORDS)]
		if bar % 4 == 0:
			place(pads, pad(notes, 4 * BAR + 1), start)
		grooving = 2 <= bar < last_bar
		for beat in range(4):
			at = start + beat * BEAT
			if grooving:
				place(drums, kick(), at)
				place(bassline, bass(root, BEAT * 0.9), at + 0.04)
			if 4 <= bar < last_bar:
				place(hats, hat() * (0.6 if beat % 2 else 0.4), at + BEAT / 2)
		for step in STAB_STEPS + ([14] if bar % 2 else []):
			at = start + step * STEP
			# the filter opens and closes slowly, the classic dub techno sweep
			cutoff = 450 + 1700 * (0.5 - 0.5 * np.cos(2 * np.pi * at / 16))
			place(stabs, stab(notes, cutoff), at)

	# everything but the kick ducks a little on every beat, so the groove breathes
	since_beat = t % BEAT
	pump = 1 - 0.35 * np.exp(-since_beat * 9) * ((t >= 2 * BAR) & (t < last_bar * BAR))

	echo_l, echo_r = dub_delay(stabs, 3 * STEP, 0.55)
	verb_l, verb_r = reverb(stabs * 0.6 + (echo_l + echo_r) * 0.5 + hats * 0.4 + pads * 0.3)
	hiss = highpass(rng.standard_normal(n), 3000) * 0.004
	crackle = lowpass((rng.random(n) < 6 / RATE) * rng.standard_normal(n), 5000) * 0.25

	centre = drums * 0.5 + bassline * 0.28 + hiss + crackle
	left = centre + pump * (stabs * 0.75 + echo_l * 0.65 + pads * 0.4 + hats * 0.05 + verb_l * 0.55)
	right = centre + pump * (stabs * 0.75 + echo_r * 0.65 + pads * 0.4 + hats * 0.06 + verb_r * 0.55)
	mix = np.stack([left, right], axis=1)

	fade = np.minimum(np.minimum(t / 1.0, (seconds - t) / 2.5), 1).clip(0)[:, None]
	mix = np.tanh(mix) * fade
	return mix / np.max(np.abs(mix)) * 0.89

if __name__ == "__main__":
	out = sys.argv[1] if len(sys.argv) > 1 else "music.wav"
	seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 30
	wavfile.write(out, RATE, (song(seconds) * 32767).astype(np.int16))
