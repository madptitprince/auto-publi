import numpy as np
import subprocess
from pathlib import Path
import wave
import struct

AUDIO_DIR = Path("assets/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_RATE = 44100
DURATION = 15.0  # 15 seconds

# Note frequencies (Hz)
NOTES = {
    "C3": 130.81, "D3": 146.83, "Eb3": 155.56, "E3": 164.81, "F3": 174.61, "G3": 196.00, "Ab3": 207.65, "A3": 220.00, "Bb3": 233.08, "B3": 246.94,
    "C4": 261.63, "Db4": 277.18, "D4": 293.66, "Eb4": 311.13, "E4": 329.63, "F4": 349.23, "Gb4": 369.99, "G4": 392.00, "Ab4": 415.30, "A4": 440.00, "Bb4": 466.16, "B4": 493.88,
    "C5": 523.25, "Db5": 554.37, "D5": 587.33, "Eb5": 622.25, "E5": 659.25, "F5": 698.46, "G5": 783.99, "A5": 880.00, "B5": 987.77,
}

DAYS_CHORDS = {
    "monday": [
        ["C3", "E4", "G4", "B4"],       # Cmaj7
        ["A3", "C4", "E4", "G4"],       # Am7
        ["F3", "A4", "C5", "E5"],       # Fmaj7
        ["G3", "B4", "D5", "F5"],       # G7
    ],
    "tuesday": [
        ["D3", "F4", "A4", "C5"],       # Dm7
        ["G3", "B4", "D5", "F5"],       # G7
        ["E3", "G4", "B4", "D5"],       # Em7
        ["A3", "C#4", "E4", "G4"],      # A7
    ],
    "wednesday": [
        ["F3", "A4", "C5", "E5"],       # Fmaj7
        ["E3", "G4", "B4", "D5"],       # Em7
        ["D3", "F4", "A4", "C5"],       # Dm7
        ["C3", "E4", "G4", "B4"],       # Cmaj7
    ],
    "thursday": [
        ["Bb3", "D4", "F4", "A4"],      # Bbmaj7
        ["A3", "C4", "E4", "G4"],       # Am7
        ["G3", "Bb4", "D5", "F5"],      # Gm7
        ["C3", "E4", "G4", "Bb4"],      # C7
    ],
    "friday": [
        ["G3", "B4", "D5", "Gb5"],      # Gmaj7
        ["B3", "D4", "Gb4", "A4"],      # Bm7
        ["C3", "E4", "G4", "B4"],       # Cmaj7
        ["D3", "Gb4", "A4", "C5"],      # D7
    ],
    "saturday": [
        ["C3", "E4", "G4", "B4"],       # Cmaj7
        ["E3", "Ab4", "B4", "D5"],      # E7
        ["A3", "C4", "E4", "G4"],       # Am7
        ["F3", "A4", "C5", "E5"],       # Fmaj7
    ],
    "sunday": [
        ["Ab3", "C4", "Eb4", "G4"],     # Abmaj7
        ["F3", "Ab4", "C5", "Eb5"],     # Fm7
        ["Bb3", "Db4", "F4", "Ab4"],    # Bbm7
        ["Eb3", "G4", "Bb4", "Db5"],    # Eb7
    ],
}

# Fix enharmonics
NOTES["C#4"] = NOTES["Db4"]
NOTES["Gb5"] = NOTES["F5"] * (2 ** (1/12))
NOTES["Gb4"] = NOTES["F4"] * (2 ** (1/12))


def synth_rhodes_note(freq: float, duration: float, sample_rate: int = 44100) -> np.ndarray:
    """Synthesizes a soft, warm Rhodes electric piano chime."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    
    # Fundamental + warm bell harmonics
    s1 = np.sin(2 * np.pi * freq * t) * np.exp(-t * 0.9)
    s2 = 0.45 * np.sin(2 * np.pi * (freq * 2.001) * t) * np.exp(-t * 1.8)
    s3 = 0.20 * np.sin(2 * np.pi * (freq * 3.003) * t) * np.exp(-t * 2.8)
    s4 = 0.08 * np.sin(2 * np.pi * (freq * 4.005) * t) * np.exp(-t * 4.0)
    
    # Soft attack (30ms)
    attack_samples = int(0.03 * sample_rate)
    attack_env = np.linspace(0, 1, attack_samples)
    env = np.ones_like(t)
    env[:attack_samples] = attack_env
    
    signal = (s1 + s2 + s3 + s4) * env
    return signal


def generate_day_audio(day_name: str, chord_progression: list[list[str]]):
    total_samples = int(SAMPLE_RATE * DURATION)
    left_channel = np.zeros(total_samples)
    right_channel = np.zeros(total_samples)
    
    chord_duration = DURATION / len(chord_progression)  # 3.75s per chord
    
    for c_idx, chord in enumerate(chord_progression):
        start_time = c_idx * chord_duration
        start_sample = int(start_time * SAMPLE_RATE)
        
        for n_idx, note_name in enumerate(chord):
            freq = NOTES.get(note_name, 261.63)
            # Strumming effect: slight delay per note (40ms)
            note_delay = n_idx * 0.04
            note_start_sample = start_sample + int(note_delay * SAMPLE_RATE)
            
            note_dur = DURATION - (note_start_sample / SAMPLE_RATE)
            if note_dur <= 0:
                continue
                
            note_wave = synth_rhodes_note(freq, note_dur, SAMPLE_RATE)
            end_sample = min(total_samples, note_start_sample + len(note_wave))
            valid_len = end_sample - note_start_sample
            
            # Subtle stereo panning across the chord
            pan = (n_idx / (len(chord) - 1)) if len(chord) > 1 else 0.5
            l_gain = np.cos(pan * np.pi / 2)
            r_gain = np.sin(pan * np.pi / 2)
            
            left_channel[note_start_sample:end_sample] += note_wave[:valid_len] * l_gain * 0.28
            right_channel[note_start_sample:end_sample] += note_wave[:valid_len] * r_gain * 0.28
            
    # Master smooth fade-in (1s) and fade-out (1.5s)
    fade_in = np.linspace(0, 1, int(1.0 * SAMPLE_RATE))
    fade_out = np.linspace(1, 0, int(1.5 * SAMPLE_RATE))
    
    left_channel[:len(fade_in)] *= fade_in
    right_channel[:len(fade_in)] *= fade_in
    left_channel[-len(fade_out):] *= fade_out
    right_channel[-len(fade_out):] *= fade_out
    
    # Normalize
    max_val = max(np.max(np.abs(left_channel)), np.max(np.abs(right_channel)), 1e-4)
    left_channel = (left_channel / max_val) * 0.88
    right_channel = (right_channel / max_val) * 0.88
    
    # Save as temporary WAV
    wav_path = AUDIO_DIR / f"{day_name}.wav"
    mp3_path = AUDIO_DIR / f"{day_name}.mp3"
    
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        interleaved = np.empty((total_samples * 2,), dtype=np.int16)
        interleaved[0::2] = (left_channel * 32767).astype(np.int16)
        interleaved[1::2] = (right_channel * 32767).astype(np.int16)
        wf.writeframes(interleaved.tobytes())
        
    # Convert to MP3 high quality via FFmpeg
    subprocess.run([
        "ffmpeg", "-y", "-i", str(wav_path),
        "-b:a", "192k",
        str(mp3_path)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    
    wav_path.unlink()
    print(f"Generated {mp3_path.name} (15s)")


if __name__ == "__main__":
    for day, chords in DAYS_CHORDS.items():
        generate_day_audio(day, chords)
