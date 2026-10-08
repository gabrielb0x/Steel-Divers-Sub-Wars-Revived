#!/usr/bin/env python3
"""BCSTM, the game's music streams (romfs:/audiores/stream/*.bcstm): read, decode, and write new ones.

    tools/bcstm.py info Title_lr.n.327.dspadpcm.bcstm
    tools/bcstm.py decode Title_lr.n.327.dspadpcm.bcstm -o titre.wav
    tools/bcstm.py encode ma-musique.wav -o Title_lr.n.327.dspadpcm.bcstm --like <original>

The game's streams are DSP-ADPCM (codec 2), 32728 Hz (22050 for two of them), mostly stereo, and loop. The music
of a mod is written as PCM16 (codec 1): no encoder to get right, nothing lost, and the stream player of the game
(nw::snd StreamSoundPlayer) reads PCM8, PCM16 and DSP-ADPCM alike; the game itself has a PCM8 stream
(audiores_SeaBattle/stream/null_s.b.32.c4.pcm8.bcstm), whose layout the writer reproduces byte for byte.

Layout (little endian, version 0x02020000):
  header   "CSTM", BOM 0xFEFF, u16 header size (0x40), u32 version, u32 file size, u16 section count, u16 0,
           then per section u16 type (0x4000 INFO, 0x4001 SEEK, 0x4002 DATA), u16 0, u32 offset, u32 size
  INFO     "INFO", u32 size, three references (u16 type, u16 0, s32 offset from INFO+8): stream info (0x4100),
           track table (none: 0, -1), channel table (0x0101)
  stream   u8 codec, u8 loops, u8 channels, u8 0, u32 sample rate, u32 loop start, u32 loop end (= samples),
           u32 blocks, u32 block size, u32 block samples, u32 last block size, u32 last block samples,
           u32 last block padded size, u32 seek entry size (4), u32 seek interval (samples), reference to the
           samples (0x1F00, offset from DATA+8: 0x18), u16 0x100, u16 0, reference (0, -1)
  channels u32 count, references (0x4102) to an entry each: a reference (0x0300) to the DSP-ADPCM state
           (16 coefficients, predictor/scale, history, the same at the loop start, padding), or (0, -1)
  SEEK     DSP-ADPCM only: the history of each channel at each block
  DATA     "DATA", u32 size, padding to 0x20, then the blocks: block after block, each channel's in turn, the
           last one padded to 0x20 bytes
Standard library only (a tool of the players: the music tab of the launcher).
"""

from __future__ import annotations

import argparse
import array
import struct
import sys
import wave
from dataclasses import dataclass, field
from pathlib import Path

PCM8, PCM16, DSP_ADPCM = 0, 1, 2
VERSION = 0x02020000
BLOCK_SIZE = 0x2000                 # bytes of a channel per block, as in every stream of the game


class BcstmError(Exception):
    pass


def _align(n: int, a: int = 0x20) -> int:
    return (n + a - 1) // a * a


@dataclass
class Stream:
    codec: int
    rate: int
    channels: int
    samples: int
    loop: bool = True
    loop_start: int = 0
    block_size: int = BLOCK_SIZE
    block_samples: int = 0
    blocks: int = 0
    last_size: int = 0
    last_samples: int = 0
    last_padded: int = 0
    adpcm: list[dict] = field(default_factory=list)       # per channel: coefs, ps, yn1, yn2
    data: bytes = b""                                       # the DATA section's samples (from its offset 0x20)

    @property
    def seconds(self) -> float:
        return self.samples / self.rate if self.rate else 0.0


def read(raw: bytes) -> Stream:
    if raw[:4] != b"CSTM" or struct.unpack_from("<H", raw, 4)[0] != 0xFEFF:
        raise BcstmError("pas un fichier BCSTM (CSTM, petit-boutiste)")
    count = struct.unpack_from("<H", raw, 0x10)[0]
    sections = {}
    for i in range(count):
        kind, _, offset, size = struct.unpack_from("<HHiI", raw, 0x14 + 12 * i)
        sections[kind] = (offset, size)
    if 0x4000 not in sections or 0x4002 not in sections:
        raise BcstmError("BCSTM sans INFO ou sans DATA")
    info = sections[0x4000][0]
    base = info + 8
    refs = [struct.unpack_from("<HHi", raw, base + 8 * i) for i in range(3)]
    si = base + refs[0][2]
    (codec, loops, channels, _, rate, loop_start, samples, blocks, block_size, block_samples, last_size,
     last_samples, last_padded) = struct.unpack_from("<BBBBIIIIIIIII", raw, si)
    stream = Stream(codec, rate, channels, samples, bool(loops), loop_start, block_size, block_samples, blocks,
                    last_size, last_samples, last_padded)
    table = base + refs[2][2]
    n = struct.unpack_from("<I", raw, table)[0]
    for c in range(n):
        entry = table + struct.unpack_from("<HHi", raw, table + 4 + 8 * c)[2]
        kind, _, offset = struct.unpack_from("<HHi", raw, entry)
        if offset != -1 and kind == 0x0300:
            values = struct.unpack_from("<16hHhh", raw, entry + offset)
            stream.adpcm.append({"coefs": list(values[:16]), "ps": values[16], "yn1": values[17], "yn2": values[18]})
    if codec not in (PCM8, PCM16, DSP_ADPCM):
        raise BcstmError(f"codage {codec} non pris en charge")
    data = sections[0x4002][0]
    stream.data = raw[data + 0x20: data + sections[0x4002][1]]
    return stream


def _blocks(stream: Stream):
    """(block, channel, bytes of that channel in that block), in the file's order."""
    offset = 0
    for b in range(stream.blocks):
        last = b == stream.blocks - 1
        size, padded = (stream.last_size, stream.last_padded) if last else (stream.block_size, stream.block_size)
        for c in range(stream.channels):
            yield b, c, stream.data[offset: offset + size]
            offset += padded


def decode(stream: Stream) -> list[array.array]:
    """Each channel's samples, signed 16 bits."""
    out = [array.array("h") for _ in range(stream.channels)]
    if stream.codec == DSP_ADPCM:
        history = [[0, 0] for _ in range(stream.channels)]
        for b, c, chunk in _blocks(stream):
            coefs = stream.adpcm[c]["coefs"]
            h = history[c]
            dest = out[c]
            yn1, yn2 = h
            for f in range(0, len(chunk), 8):
                header = chunk[f]
                c1, c2 = coefs[2 * (header >> 4)], coefs[2 * (header >> 4) + 1]
                scale = 1 << (header & 15)
                for byte in chunk[f + 1: f + 8]:
                    for nibble in (byte >> 4, byte & 15):
                        if nibble >= 8:
                            nibble -= 16
                        s = (nibble * scale * 2048 + 1024 + c1 * yn1 + c2 * yn2) >> 11
                        s = -32768 if s < -32768 else 32767 if s > 32767 else s
                        dest.append(s)
                        yn2, yn1 = yn1, s
            h[0], h[1] = yn1, yn2
    else:
        for b, c, chunk in _blocks(stream):
            if stream.codec == PCM16:
                values = array.array("h", chunk[: len(chunk) // 2 * 2])
                if sys.byteorder == "big":
                    values.byteswap()
            else:
                values = array.array("h", ((x - 256 if x > 127 else x) * 256 for x in chunk))
            out[c].extend(values)
    for c in out:
        del c[stream.samples:]
    return out


def write(channels: list[array.array], rate: int, loop: bool = True, loop_start: int = 0, codec: int = PCM16,
          block_size: int = BLOCK_SIZE) -> bytes:
    """A PCM16 (or PCM8) stream of these channels."""
    if codec not in (PCM8, PCM16):
        raise BcstmError("seuls PCM8 et PCM16 s'écrivent")
    count = len(channels)
    samples = len(channels[0]) if channels else 0
    if not 1 <= count <= 2 or any(len(c) != samples for c in channels) or not samples:
        raise BcstmError("1 ou 2 canaux de même longueur, non vides")
    width = 2 if codec == PCM16 else 1
    block_samples = block_size // width
    blocks = (samples + block_samples - 1) // block_samples
    last_samples = samples - (blocks - 1) * block_samples
    last_size = last_samples * width
    last_padded = _align(last_size)
    loop_start = loop_start if loop else 0

    info = bytearray(b"INFO\0\0\0\0")
    info += struct.pack("<HHi", 0x4100, 0, 0x18) + struct.pack("<HHi", 0, 0, -1) + struct.pack("<HHi", 0x0101, 0, 0x5C)
    info += struct.pack("<BBBBIIIIIIIIIII", codec, int(loop), count, 0, rate, loop_start, samples, blocks, block_size,
                        block_samples, last_size, last_samples, last_padded, 4, block_samples)
    info += struct.pack("<HHi", 0x1F00, 0, 0x18) + struct.pack("<HH", 0x100, 0) + struct.pack("<HHi", 0, 0, -1)
    info += struct.pack("<I", count)
    for c in range(count):
        info += struct.pack("<HHi", 0x4102, 0, 4 + 8 * count + 8 * c)
    for c in range(count):
        info += struct.pack("<HHi", 0, 0, -1)
    info += bytes(_align(len(info)) - len(info))
    struct.pack_into("<I", info, 4, len(info))

    body = bytearray()
    for b in range(blocks):
        start = b * block_samples
        n = block_samples if b < blocks - 1 else last_samples
        for c in range(count):
            part = channels[c][start: start + n]
            if codec == PCM16:
                part = array.array("h", part)
                if sys.byteorder == "big":
                    part.byteswap()
                chunk = part.tobytes()
            else:
                chunk = bytes((v >> 8) & 0xFF for v in part)
            body += chunk + bytes((block_size if b < blocks - 1 else last_padded) - len(chunk))
    data = bytearray(b"DATA\0\0\0\0") + bytes(0x18) + body
    struct.pack_into("<I", data, 4, len(data))

    header = bytearray(0x40)
    info_at = 0x40
    data_at = info_at + len(info)
    total = data_at + len(data)
    struct.pack_into("<4sHHIIHH", header, 0, b"CSTM", 0xFEFF, 0x40, VERSION, total, 2, 0)
    struct.pack_into("<HHiI", header, 0x14, 0x4000, 0, info_at, len(info))
    struct.pack_into("<HHiI", header, 0x20, 0x4002, 0, data_at, len(data))
    return bytes(header + info + data)


# ---- WAV, and making a stream from any WAV --------------------------------------------------------

def read_wav(path: Path) -> tuple[list[array.array], int]:
    """The channels of a PCM WAV (8, 16, 24 or 32 bits) as 16 bits, and its rate."""
    try:
        with wave.open(str(path), "rb") as w:
            count, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(frames)
    except (wave.Error, EOFError) as e:
        raise BcstmError(f"{path.name} : WAV illisible ({e}) ; seuls les WAV PCM se lisent ici") from e
    if width == 2:
        values = array.array("h", raw[: len(raw) // 2 * 2])
        if sys.byteorder == "big":
            values.byteswap()
    elif width == 1:
        values = array.array("h", ((x - 128) * 256 for x in raw))
    elif width in (3, 4):
        values = array.array("h", (int.from_bytes(raw[i + width - 2: i + width], "little", signed=True)
                                   for i in range(0, len(raw) - width + 1, width)))
    else:
        raise BcstmError(f"{path.name} : échantillons de {width} octets non pris en charge")
    return [values[c::count] for c in range(count)], rate


def write_wav(path, channels: list[array.array], rate: int) -> None:
    """A 16-bit WAV, to a path or a binary file object."""
    interleaved = array.array("h", bytes(2 * len(channels[0]) * len(channels)))
    for c, values in enumerate(channels):
        interleaved[c::len(channels)] = values
    if sys.byteorder == "big":
        interleaved.byteswap()
    with wave.open(path if hasattr(path, "write") else str(path), "wb") as w:
        w.setnchannels(len(channels))
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(interleaved.tobytes())


def resample(values: array.array, source: int, target: int) -> array.array:
    """Linear interpolation (the launcher's page converts with the browser's resampler; this is for the
    command line)."""
    if source == target or not values:
        return array.array("h", values)
    n = max(1, round(len(values) * target / source))
    step = source / target
    out = array.array("h", bytes(2 * n))
    last = len(values) - 1
    for i in range(n):
        x = i * step
        k = int(x)
        if k >= last:
            out[i] = values[last]
        else:
            t = x - k
            out[i] = int(values[k] + (values[k + 1] - values[k]) * t)
    return out


def fit(channels: list[array.array], rate: int, like: Stream) -> list[array.array]:
    """Channels and rate of the stream this music replaces: the game's sound archive allots its voices."""
    if len(channels) != like.channels:
        if like.channels == 1:
            mono = array.array("h", ((sum(v) // len(channels)) for v in zip(*channels)))
            channels = [mono]
        else:
            channels = [channels[0], channels[0]] if len(channels) == 1 else channels[:2]
    return [resample(c, rate, like.rate) for c in channels]


def replacement(music: list[array.array], rate: int, original: bytes) -> bytes:
    """The stream that replaces original: same channels and rate, looping from the start as the game's
    music does."""
    like = read(original)
    channels = fit(music, rate, like)
    return write(channels, like.rate, loop=like.loop, loop_start=0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("info", help="ce que contient un flux")
    p.add_argument("files", nargs="+", type=Path)
    p = sub.add_parser("decode", help="un flux -> WAV")
    p.add_argument("file", type=Path)
    p.add_argument("-o", "--out", type=Path)
    p = sub.add_parser("encode", help="WAV -> flux PCM16 (mêmes canaux et fréquence que l'original)")
    p.add_argument("file", type=Path)
    p.add_argument("--like", type=Path, required=True, help="le flux du jeu qu'il remplace")
    p.add_argument("-o", "--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "info":
            for path in args.files:
                s = read(path.read_bytes())
                print(f"{path.name}: {['PCM8', 'PCM16', 'DSP-ADPCM'][s.codec]}, {s.channels} canal(aux), {s.rate} Hz, "
                      f"{s.seconds:.1f} s" + (f", boucle depuis {s.loop_start / s.rate:.1f} s" if s.loop else ""))
        elif args.command == "decode":
            s = read(args.file.read_bytes())
            out = args.out or args.file.with_suffix(".wav")
            write_wav(out, decode(s), s.rate)
            print(f"{out} ({s.seconds:.1f} s)")
        else:
            music, rate = read_wav(args.file)
            args.out.write_bytes(replacement(music, rate, args.like.read_bytes()))
            print(args.out)
    except (BcstmError, OSError) as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
