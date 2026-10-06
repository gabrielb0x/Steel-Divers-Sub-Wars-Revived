"""Tests of the players' tools that need no game file: ARM assembler, save format, recipes, shaders.

    python3 -m unittest discover -s tools/tests
"""

import json
import socket
import struct
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zlib
from pathlib import Path
import xml.etree.ElementTree as ET
from unittest import mock

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))

import azahar                                  # noqa: E402
import mod                                     # noqa: E402
import shbin                                   # noqa: E402
import versions                                # noqa: E402
from amx import disassemble                    # noqa: E402
from amxasm import AmxImage, AsmError as AmxAsmError   # noqa: E402
import webui                                   # noqa: E402
from armasm import AsmError, assemble          # noqa: E402
from save import SaveData, SaveError, parse_value   # noqa: E402

# Encodings produced by keystone 0.9.2 (LLVM) at 0x0013A098, the reference of the assembler.
KEYSTONE = [
    ('mov r0, #1', "0100a0e3"),
    ('mov r0, #0', "0000a0e3"),
    ('mvn r0, #0', "0000e0e3"),
    ('mov r0, #-1', "0000e0e3"),
    ('mov r2, #0x138', "4e2fa0e3"),
    ('mov r1, #200', "c810a0e3"),
    ('movs r1, r2', "0210b0e1"),
    ('moveq r3, r4, lsl #2', "0431a001"),
    ('mov r0, r0, lsr #32', "2000a0e1"),
    ('mov r1, r2, asr r3', "5213a0e1"),
    ('mov r1, r2, ror #8', "6214a0e1"),
    ('mov r1, r2, rrx', "6210a0e1"),
    ('add r0, r4, #8', "080084e2"),
    ('add r0, r4, #0x30', "300084e2"),
    ('add sp, sp, #0x80', "80d08de2"),
    ('sub sp, sp, #0x80', "80d04de2"),
    ('subs r2, r2, #4', "042052e2"),
    ('add r1, r1, #1', "011081e2"),
    ('add r0, r1, r2, lsl #2', "020181e0"),
    ('addne r0, r1, r2', "02008110"),
    ('add r0, #4', "040080e2"),
    ('cmp r1, #32', "200051e3"),
    ('cmp r2, #0', "000052e3"),
    ('cmp r1, #-1', "010071e3"),
    ('cmp r0, r1', "010050e1"),
    ('tst r0, #0x80000000', "020110e3"),
    ('teq r1, r2', "020031e1"),
    ('cmn r3, #5', "050073e3"),
    ('orr r0, r0, #0xff00', "ff0c80e3"),
    ('and r0, r1, #0xff', "ff0001e2"),
    ('bic r0, r0, #3', "0300c0e3"),
    ('eor r0, r0, r0', "000020e0"),
    ('rsb r0, r0, #0', "000060e2"),
    ('adc r0, r1, r2', "0200a1e0"),
    ('sbc r0, r1, #1', "0100c1e2"),
    ('mul r0, r1, r2', "910200e0"),
    ('muls r0, r1, r2', "910210e0"),
    ('mla r0, r1, r2, r3', "913220e0"),
    ('str r0, [sp, r1, lsl #2]', "01018de7"),
    ('str r1, [r4, r2]', "021084e7"),
    ('str r1, [r4]', "001084e5"),
    ('str r1, [r4, #4]', "041084e5"),
    ('str r1, [r4, #-4]', "041004e5"),
    ('str r1, [r4, #-4]!', "041024e5"),
    ('ldr r1, [r4], #4', "041094e4"),
    ('ldr r1, [r4], #-4', "041014e4"),
    ('ldr r0, [r0, #0xfa8]', "a80f90e5"),
    ('ldr r0, [r1, -r2]', "020011e7"),
    ('ldr r0, [r1, r2, asr #3]', "c20191e7"),
    ('ldrb r2, [r1], #1', "0120d1e4"),
    ('strb r2, [r0], #1', "0120c0e4"),
    ('ldrb r0, [r1, #3]', "0300d1e5"),
    ('strb r0, [r1, -r2]', "020041e7"),
    ('ldrbne r2, [r1], #1', "0120d114"),
    ('strh r1, [r4, #0x28]', "b812c4e1"),
    ('ldrh r1, [r4, #2]', "b210d4e1"),
    ('ldrh r1, [r4, #-2]', "b21054e1"),
    ('ldrh r1, [r4, r5]', "b51094e1"),
    ('ldrh r1, [r4], #2', "b210d4e0"),
    ('ldrh r1, [r4, #2]!', "b210f4e1"),
    ('ldrsh r1, [r4, #2]', "f210d4e1"),
    ('ldrsb r1, [r4, #2]', "d210d4e1"),
    ('strh r1, [r4, -r5]', "b51004e1"),
    ('push {r4, lr}', "10402de9"),
    ('pop {r4, pc}', "1080bde8"),
    ('push {r4-r6, lr}', "70402de9"),
    ('push {r4}', "04402de5"),
    ('pop {r4}', "04409de4"),
    ('push {r0, r1, r2, r3, r4, r5, r6, r7, r8, r9, r10, r11, r12, lr}', "ff5f2de9"),
    ('stmdb sp!, {r4, r5}', "30002de9"),
    ('ldmia sp!, {r4, r5}', "3000bde8"),
    ('ldmfd sp!, {r0, r1}', "0300bde8"),
    ('stmfd sp!, {r0, r1}', "03002de9"),
    ('ldm r0, {r1, r2}', "060090e8"),
    ('stmia r0!, {r1}', "0200a0e8"),
    ('bx lr', "1eff2fe1"),
    ('nop', "00f020e3"),
    ('bxne r3', "13ff2f11"),
    ('blx r3', "33ff2fe1"),
    ('.word 0x1234', "34120000"),
    ('.word 1, 2, 3', "010000000200000003000000"),
    ('.short 5', "0500"),
    ('.byte 1, 2, 255', "0102ff"),
    ('.asciz "save.sub.unlock"', "736176652e7375622e756e6c6f636b00"),
    ('.ascii "abc"', "616263"),
    ('.align 2', ""),
    ('vldr s0, [r1, #4]', "010a91ed"),
    ('vldr s31, [r2, #-8]', "02fa52ed"),
    ('vstr s17, [sp, #-1020]', "ff8a4ded"),
    ('vldr d8, [r4, #16]', "048b94ed"),
    ('vadd.f32 s31, s30, s29', "2efa7fee"),
    ('vsub.f32 s3, s4, s5', "621a72ee"),
    ('vmul.f32 s16, s17, s18', "898a28ee"),
    ('vdiv.f32 s0, s0, s1', "200a80ee"),
    ('vaddeq.f32 s0, s1, s2', "810a300e"),
    ('vmov s17, r12', "90ca08ee"),
    ('vmov lr, s30', "10ea1fee"),
    ('vmov.f32 s31, s0', "40faf0ee"),
    ('vcmpe.f32 s15, s16', "c87af4ee"),
    ('vcmp.f32 s3, #0', "401af5ee"),
    ('vmrs APSR_nzcv, fpscr', "10faf1ee"),
    ('vpush {d8-d10}', "068b2ded"),
    ('vpop {s16-s19}', "048abdec"),
]


class Assembler(unittest.TestCase):
    def test_same_encodings_as_keystone(self):
        for line, expected in KEYSTONE:
            with self.subTest(line=line):
                self.assertEqual(assemble(line, 0x13A098).hex(), expected)

    def test_labels_branches_and_literals(self):
        code = assemble("""
            push {r4, lr}
            b skip
            bl 0x001DA344
        skip:
            bne skip
            blt back
        back:
            adr r0, data
            ldr r1, data
            ldr r2, back
            adr r3, back
            bls back
            bleq back           @ keystone gets this one wrong (it leaves a branch to itself)
            bhi far
            pop {r4, pc}
        data:
            .word 7
        far:
            .asciz "x"
            .align 2
        """, 0x2F0000)
        self.assertEqual(code.hex(), "10402de9000000eacda8fbebfeffff1affffffba18008fe214109fe510201fe514304fe2"
                                     "faffff9af9ffff0b0100008a1080bde80700000078000000")

    def test_recipes_assemble(self):
        params = {"pid": "305419896", "password": "abcdefgh12345678", "token": "sdsw1:" + "0" * 32,
                  "port": "61000", "server": "127.0.0.1", "debloquer": "oui", "dlc": "non"}
        from string import Template
        for recipe in sorted((TOOLS.parent / "mods").glob("*/mod.toml")):
            data = tomllib.loads(recipe.read_text(encoding="utf-8"))
            for version in mod.recipe_versions(data) or ["v0"]:
                resolved = mod.for_version(data, version, recipe.parent.name)
                values = dict(params)                   # the labels of an entry are ${arm_<label>} after it
                values.update({k: f"{v:#010x}" if isinstance(v, int) else v
                               for k, v in resolved.get("symbols", {}).items()})
                for entry in resolved.get("code", []):
                    if version not in entry.get("versions", [version]):
                        continue
                    address = mod.entry_address(entry, values)
                    if "arm" in entry:
                        with self.subTest(recipe=recipe.parent.name, version=version, address=hex(address)):
                            symbols = {}
                            code = assemble(Template(entry["arm"]).safe_substitute(values), address, symbols)
                            values.update({f"arm_{k}": f"{v:#x}" for k, v in symbols.items()})
                            self.assertLessEqual(len(code), entry.get("max_size", len(code)))

    def test_errors(self):
        for line in ("mov r0, #0x12345", "ldr r0, [r1, #4096]", "b nowhere", "frob r0", "strsb r0, [r1]"):
            with self.subTest(line=line), self.assertRaises(AsmError):
                assemble(line, 0)


class Save(unittest.TestCase):
    def sample(self) -> bytes:
        body = struct.pack("<III", 27, 2, 1)
        body += b"save.sub.typenum\0" + struct.pack("<i", 3)
        body += b"save.single.stage1.medal[1]\0" + struct.pack("<i", 2)
        body += b"save.sub.unlock\0" + struct.pack("<I3i", 3, 1, 0, 0)
        return struct.pack("<I", zlib.crc32(body)) + body

    def test_round_trip(self):
        data = self.sample()
        save = SaveData.parse(data)
        self.assertEqual(save.ints["save.sub.typenum"], 3)
        self.assertEqual(save.arrays["save.sub.unlock"], [1, 0, 0])
        self.assertEqual(save.to_bytes(), data)

    def test_bad_crc(self):
        data = bytearray(self.sample())
        data[-1] ^= 1
        with self.assertRaises(SaveError):
            SaveData.parse(bytes(data))

    def test_unlocks(self):
        save = SaveData.parse(self.sample())
        self.assertEqual(save.unlock_subs(), 22)          # the stored array is short: padded to 23
        self.assertEqual(save.arrays["save.sub.unlock"], [1] * 23)
        self.assertEqual(save.award_medals(1), 20)        # 21 missions, one already has a medal
        self.assertEqual(save.medal(1, 1), 2)             # a gold medal stays gold
        save.set("save.sub.enlist", 1)
        self.assertTrue(save.premium_off())
        self.assertEqual(SaveData.parse(save.to_bytes()).ints["save.sub.enlist"], 0)

    def test_unlocks_of_the_update(self):
        """v5200 keeps save.sub.unlock[23] and holds its 39 submarines in save.sub.unlock2[36] and
        save.p3.sub.unlock[3], and more crew in save.p3.sub.crew.unlock[8]."""
        import save
        data = SaveData.parse(self.sample())
        self.assertEqual(len(data.unlocked_subs("v5200")), 39)
        self.assertEqual(data.unlock_subs("v5200"), 38)
        self.assertEqual([len(data.arrays[n]) for n in ("save.sub.unlock", "save.sub.unlock2", "save.p3.sub.unlock")],
                         [23, 36, 3])
        self.assertTrue(all(data.unlocked_subs("v5200")))
        self.assertEqual(data.unlock_crew("v5200"), 40)
        self.assertEqual(data.crew_unlocked("v5200"), (40, 40))
        self.assertEqual(save.sub_count("v5200"), 39)
        texts = {"sub_icon_name00": "Garfish", "sub_icon_name01": "\\x0e(70)Garfish\\x0e(142.85714285714286)"}
        self.assertEqual(save.sub_name(texts, 0), "Garfish")
        self.assertEqual(save.sub_name(texts, 0, "v5200"), "Garfish")       # numbered from 1, width codes removed

    def test_values(self):
        self.assertEqual(parse_value("0x10"), 16)
        self.assertEqual(parse_value("1,0,1"), [1, 0, 1])
        self.assertEqual(parse_value("1.5"), struct.unpack("<i", struct.pack("<f", 1.5))[0])
        with self.assertRaises(SaveError):
            SaveData().set("player.sub", 1)               # not saved by the game


def make_shbin(code: list[int]) -> bytes:
    """A DVLB with one geometry program over code, and the operand descriptors of the instructions used."""
    dvlp = struct.pack("<4sIIIII", b"DVLP", 0, 0x20, len(code), 0x20 + 4 * len(code), 1) + b"\0" * 8
    dvlp += struct.pack(f"<{len(code)}I", *code) + struct.pack("<II", 0x0000036F, 0)
    dvle = struct.pack("<4sHBBIIHHBBBBIIIIIIIIII", b"DVLE", 0x1002, 1, 0, 0, len(code), 3, 0x7F, 0, 0, 0, 0,
                       0x40, 0, 0x40, 0, 0x40, 0, 0x40, 0, 0x40, 1) + b"\0"
    header_size = 8 + 4
    return struct.pack("<4sII", b"DVLB", 1, header_size + len(dvlp)) + dvlp + dvle


# The pattern of shaders/metaball.shbin: main loops (i0) over a call of a subroutine that loops (i1).
NESTED = [0x90000C05,      # 000: call 003, 5
          0x88000000,      # 001: end
          0x84000000,      # 002: nop
          0xA4401C00,      # 003: loop i1, 007
          0xA8000000,      # 004: emit
          0x84000000,      # 005: nop
          0x84000000,      # 006: nop
          0x84000000,      # 007: nop
          0xA4002800,      # 008: loop i0, 00a
          0x90000C05,      # 009: call 003, 5
          0x84000000,      # 00a: nop
          0x88000000]      # 00b: end


class Shaders(unittest.TestCase):
    def test_disassembly(self):
        shader = shbin.Shader(make_shbin(NESTED))
        self.assertEqual(shader.disassemble(8), "loop i0, 00a")
        self.assertEqual(shader.disassemble(9), "call 003, 5")
        self.assertEqual(shader.disassemble(3), "loop i1, 007")
        self.assertEqual(shbin.disassemble(0x4C403015, [0x0000036F] * 0x16), "mov o2.xyzw, v3")
        self.assertEqual(shbin.f24(0x3F0000), 1.0)

    def test_nested_loops(self):
        self.assertEqual(shbin.Shader(make_shbin(NESTED)).nested_loops(), [(8, 3)])
        fixed = [shbin.NOP if i in (3, 8) else word for i, word in enumerate(NESTED)]
        self.assertEqual(shbin.Shader(make_shbin(fixed)).nested_loops(), [])

    def test_recipe_patch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shaders" / "test.shbin"
            path.parent.mkdir()
            path.write_bytes(make_shbin(NESTED))
            old, mod.GAME = mod.GAME, versions.GameFiles("v0", Path(folder) / "code.bin", (Path(folder),))
            try:
                shaders: dict[str, bytearray] = {}
                entry = {"file": "shaders/test.shbin", "instruction": 8, "expect": 0xA4002800, "value": shbin.NOP}
                mod.edit_shader(shaders, entry)
                self.assertEqual(shbin.Shader(bytes(shaders["shaders/test.shbin"])).code[8], shbin.NOP)
                with self.assertRaises(mod.ModError):                    # no longer the original
                    mod.edit_shader(shaders, entry)
                with self.assertRaises(mod.ModError):
                    mod.edit_shader(shaders, {"file": "shaders/test.shbin", "instruction": 99, "value": 0})
            finally:
                mod.GAME = old


def make_amx() -> bytes:
    """A compact Pawn 3.3 script: main() calls f(1) and returns; f(x) returns x ? x : 7 (a branch),
    one public (@main), one native (sysGetGlobal), a global and a string in the data."""
    from amx import OP, compress
    code = [OP["PROC"],                                         # 0x00 main
            OP["PUSH_C"], 1, OP["PUSH_C"], 4, OP["CALL"], 0x14,  # 0x04, 0x0c, 0x14: call f (0x28)
            OP["ZERO_PRI"], OP["RETN"],                         # 0x1c, 0x20
            OP["NOP"],                                          # 0x24
            OP["PROC"],                                         # 0x28 f
            OP["LOAD_S_PRI"], 12,                               # 0x2c
            OP["JNZ"], 0x10,                                    # 0x34: -> 0x44
            OP["CONST_PRI"], 7,                                 # 0x3c
            OP["RETN"]]                                         # 0x44
    data = [5] + [ord(c) for c in "abc"] + [0]
    names = b"\x0c\x00@main\0sysGetGlobal\0"
    tables = struct.pack("<II", 0, 78) + struct.pack("<II", 0, 84)       # name table at 76: u16, then names
    prefix_len = 60 + 16 + len(names)
    prefix_len += -prefix_len % 4
    body = compress(b"".join(struct.pack("<i", c) for c in code + data))
    cod = prefix_len
    dat = cod + 4 * len(code)
    hea = dat + 4 * len(data)
    header = struct.pack("<iHBBhh12i", prefix_len + len(body), 0xF1E0, 10, 10, 0x04, 8, cod, dat, hea, hea + 0x100,
                         0, 60, 68, 76, 76, 76, 76, 76)
    prefix = header + tables + names
    return prefix + bytes(prefix_len - len(prefix)) + body


class PawnAssembler(unittest.TestCase):
    def test_round_trip(self):
        raw = make_amx()
        self.assertEqual(AmxImage.parse(raw).write(), raw)

    def test_hook_function_and_public(self):
        from amx import OP, AmxFile, decode
        img = AmxImage.parse(make_amx())
        img.assemble("""
            .var $count
        .hook 0x34                      ; the jnz of f, moved by .original
            inc $count
            .original
            .return
        .public @helper
        helper:
            proc
            push.c "x.y"
            sysreq.n sysGetGlobal, 1
            push.c 2
            sysreq.n sysSetGlobal, 1
            retn
        """)
        raw = img.write()
        again = AmxImage.parse(raw)
        self.assertEqual([n for _, n, _ in again.natives], ["sysGetGlobal", "sysSetGlobal"])
        self.assertEqual([n for _, n, _ in again.publics], ["@helper", "@main"])          # sorted by name
        insns = {i.addr: i for i in decode(bytes(again.code))}
        self.assertEqual(insns[0x34].op, OP["JUMP"])
        hook = 0x34 + insns[0x34].args[0]
        self.assertEqual(insns[hook].op, OP["INC"])
        moved = insns[hook + 8]
        self.assertEqual((moved.op, moved.addr + moved.args[0]), (OP["JNZ"], 0x44))       # still goes to 0x44
        back = insns[hook + 16]
        self.assertEqual((back.op, back.addr + back.args[0]), (OP["JUMP"], 0x3c))
        self.assertEqual(again.string(img.strings["x.y"]), ("x.y", False, 4))
        with tempfile.TemporaryDirectory() as folder:                              # the disassembler reads it
            path = Path(folder) / "t.amx"
            path.write_bytes(raw)
            self.assertIn("sysSetGlobal", disassemble(AmxFile.load(path)))

    def test_data_at(self):
        img = AmxImage.parse(make_amx())
        img.assemble(".data_at 20\n.cells $x 1, 2")                # the data ends at 20: ours goes there
        self.assertEqual(img.data_labels["$x"], 20)
        with self.assertRaises(AmxAsmError):
            img.assemble(".data_at 20\n.cells $y 3")               # no longer the first to add data

    def test_compiled_pawn(self):
        """tools/pawn2pasm.py: the compiler's listing -> amxasm, the game's functions called at their address."""
        import pawn2pasm
        listing = """CODE 0000\t; 00000000
;program exit point
\thalt 0

DATA 0000\t; 00000000
dump 00000000 00000000

CODE 0000\t; 00000008
\tproc\t; spawn
\tzero.pri
\tretn

\tproc\t; @eventCollide
\tload.s.pri 0000000c
\tjzer 00000001
\tadd.c -00000001
\tpush.c 00000008
\tsysreq.c 00000000\t; floatmul
\tpush.c 00000000
\tcall spawn
l.00000001
\tzero.pri
\tretn

DATA 0000\t; 00000008
dump 00000041 00000000
"""
        code, cells = pawn2pasm.convert(listing, ["floatmul"], ["@eventCollide"], {"spawn": 0x2ea0}, 8, "m")
        self.assertEqual(code, [".public @eventCollide", "pw_at_eventCollide:", "    proc", "    load.s.pri 0xc",
                                "    jzer @m_l1", "    add.c -1", "    push.c 0x8", "    sysreq.c floatmul",
                                "    push.c 0x0", "    call 0x2ea0", "m_l1:", "    zero.pri", "    retn"])
        self.assertEqual(cells, ["0x41", "0x0"])
        with self.assertRaises(pawn2pasm.Pawn2PasmError):          # the game's globals have no initial value
            pawn2pasm.convert(listing, ["floatmul"], [], {}, 12, "m")
        head, calls, _ = pawn2pasm.prelude("// @game Float:g_0008[2]  position\n"
                                           "// @call 0x2ea0 spawn(const name[])  the game's\n", 0x20)
        self.assertIn("new __game0[2];\nnew Float:g_0008[2];\nnew __game_end[4];", head)
        self.assertEqual(calls, {"spawn": 0x2ea0})

    def test_refusals(self):
        for source in (".hook 0x24\n.return",                     # nop, then a PROC: cannot be moved
                       "jump @nowhere",
                       "frob 1",
                       ".hook 0x34\n.return\n.hook 0x34\n.return"):   # twice the same place
            with self.subTest(source=source), self.assertRaises(AmxAsmError):
                AmxImage.parse(make_amx()).assemble(source)


def make_update_cia(version: int = 5200) -> bytes:
    """A decrypted CIA of the update: certificate chain, ticket and TMD (RSA-2048 signatures), one content: a
    NCCH header (program id 0004000E000D7E00, NoCrypto)."""
    def signed(body: bytes) -> bytes:
        return struct.pack(">I", 0x10004) + bytes(0x100 + 0x3C) + body
    def align(blob: bytes) -> bytes:
        return blob + bytes(-len(blob) % 64)
    ncch = bytearray(0x200)
    ncch[0x100:0x104] = b"NCCH"
    struct.pack_into("<Q", ncch, 0x108, 0x0004000E000D7E00)
    struct.pack_into("<Q", ncch, 0x118, 0x0004000E000D7E00)
    ncch[0x18F] = 0x04
    tmd_body = bytearray(0xC4 + 64 * 0x24 + 0x30)
    struct.pack_into(">QH", tmd_body, 0x4C, 0x0004000E000D7E00, 0)
    struct.pack_into(">HH", tmd_body, 0x9C, version, 1)
    struct.pack_into(">IHHQ", tmd_body, 0xC4 + 64 * 0x24, 6, 0, 0, len(ncch))
    tmd = signed(bytes(tmd_body))
    ticket = signed(bytes(0x164))
    certs = bytes(0x40)
    header = bytearray(0x2020)
    struct.pack_into("<IHHIIIIQ", header, 0, 0x2020, 0, 0, len(certs), len(ticket), len(tmd), 0, len(ncch))
    header[0x20] = 0x80
    return align(bytes(header)) + align(certs) + align(ticket) + align(tmd) + bytes(ncch)


class Versions(unittest.TestCase):
    def test_layers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for path, text in (("romfs/a.bxml", "base"), ("romfs/b.bxml", "base"), ("v5200/romfs/a.bxml", "update"),
                               ("v5200/romfs/c.bxml", "new")):
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text(text)
            with mock.patch.object(versions, "EXTRACTED", root):
                game = versions.game_files("v5200")
                self.assertEqual(game.path("a.bxml").read_text(), "update")
                self.assertEqual(game.path("b.bxml").read_text(), "base")
                self.assertEqual(game.glob("*.bxml"), ["a.bxml", "b.bxml", "c.bxml"])
                self.assertEqual(versions.game_files("v0").glob("*.bxml"), ["a.bxml", "b.bxml"])
                self.assertEqual(versions.extracted_versions(), [])          # no code.bin, no manifest
                (root / "code.bin").write_bytes(b"")
                (root / "v5200" / "code.bin").write_bytes(b"")
                (root / "v5200" / "manifest.json").write_text("{}")
                self.assertEqual(versions.extracted_versions(), ["v0", "v5200"])

    def test_update_in_an_emulator(self):
        """The update installed as Azahar does it is found, with its version; uninstalled, the game is v0 again."""
        with tempfile.TemporaryDirectory() as folder:
            base, cia = Path(folder) / "user", Path(folder) / "update.cia"
            cia.write_bytes(make_update_cia())
            self.assertEqual(versions.emulator_version(base), "v0")
            content = azahar.install_update(cia, base)
            self.assertEqual(sorted(p.name for p in content.iterdir()), ["00000000.tmd", "00000006.app"])
            self.assertEqual(content.relative_to(base).as_posix(), "sdmc/Nintendo 3DS/" + "0" * 32 + "/" + "0" * 32
                             + "/title/0004000e/000d7e00/content")
            self.assertEqual(versions.installed_update(base), (5200, content / "00000006.app"))
            self.assertEqual(versions.emulator_version(base), "v5200")
            self.assertEqual(azahar.uninstall_update(base), [content.parent])
            self.assertEqual(versions.emulator_version(base), "v0")

    def test_installed_mods_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            self.assertIsNone(azahar.installed_mods(base))
            mods = base / "load" / "mods" / azahar.TITLE_ID
            mods.mkdir(parents=True)
            self.assertEqual(azahar.installed_mods(base), {})              # installed before the markers
            (mods / azahar.MARKER).write_text('{"version": "v5200", "mods": ["correctifs"]}')
            self.assertEqual(azahar.installed_mods(base)["version"], "v5200")


class Emulators(unittest.TestCase):
    def test_every_emulator_of_the_citra_family(self):
        import azahar
        with tempfile.TemporaryDirectory() as home:
            home = Path(home)
            for folder in ("AppData/Roaming/Azahar", "AppData/Roaming/Borked3DS",
                           "Library/Application Support/Lime3DS", ".local/share/citra-emu",
                           ".var/app/org.azahar_emu.Azahar/data/azahar-emu"):
                (home / folder).mkdir(parents=True)
            env = {"APPDATA": str(home / "AppData/Roaming"), "XDG_DATA_HOME": str(home / ".local/share")}
            with mock.patch.dict("os.environ", env), mock.patch("pathlib.Path.home", return_value=home):
                found = azahar.emulator_dirs()
        names = [name for name, _ in found]
        self.assertEqual(names, ["Azahar (Flatpak)", "Azahar", "Lime3DS", "Citra", "Borked3DS"])


class Recipes(unittest.TestCase):
    def test_scale(self):
        self.assertEqual(mod.scaled("0.36", 15), "5.4")
        self.assertEqual(mod.scaled("0.4", 10), "4.0")                 # stays a f32
        self.assertEqual(mod.scaled("3 -2", 2), "6 -4")
        self.assertEqual(mod.scaled("n2ply_s001", 2), "n2ply_s001")

    def test_choices(self):
        recipe = {"params": {"facteur": {"default": "2", "choices": ["2", "3", "5"]}}}
        self.assertEqual(mod.recipe_params([recipe], {"facteur": "5"})["facteur"], "5")
        with self.assertRaises(mod.ModError):
            mod.recipe_params([recipe], {"facteur": "4"})

    def test_new_and_appended_texts(self):
        files = {"text/EU_French.bxml": ET.fromstring(
            '<text><string key="a" text="A" typeface="f"/><string key="title" text="Titre"/></text>')}
        mod.apply_texts(files, {"key": "new", "like": "a", "text": "N ${x}", "languages": ["EU_French"]},
                        {"x": "1"})
        mod.apply_texts(files, {"key": "title", "append": "\nv${v}", "languages": ["EU_French"]}, {"v": "2"})
        root = files["text/EU_French.bxml"]
        self.assertEqual([(n.get("key"), n.get("text"), n.get("typeface")) for n in root],
                         [("a", "A", "f"), ("new", "N 1", "f"), ("title", "Titre\\nv2", None)])
        self.assertTrue(mod.project_version().startswith("v"))

    def test_version_tables(self):
        entry = {"address": {"v0": 0x100, "v5200": 0x200}, "set": {"timeLimit": "1"}, "list": [{"v0": 1, "v5200": 2}]}
        self.assertEqual(mod.for_version(entry, "v5200"), {"address": 0x200, "set": {"timeLimit": "1"}, "list": [2]})
        with self.assertRaises(mod.ModError):
            mod.for_version(entry, "v1024")
        self.assertTrue(mod.supports({"versions": ["v0"]}, "v0"))
        self.assertFalse(mod.supports({"versions": ["v0"]}, "v5200"))
        self.assertTrue(mod.supports({}, "v5200"))                     # data by name only: any version
        self.assertEqual(mod.entry_address({"address": "${f}"}, {"f": "0x00123456"}), 0x123456)

    def test_recipes_declare_their_versions(self):
        """A recipe that patches by address (code, script, shader) says which versions it was written for, and
        gives every value that depends on the version for each of them."""
        for recipe in sorted((TOOLS.parent / "mods").glob("*/mod.toml")):
            data = tomllib.loads(recipe.read_text(encoding="utf-8"))
            with self.subTest(recipe=recipe.parent.name):
                if any(data.get(kind) for kind in ("code", "amx", "shader")):
                    self.assertTrue(mod.recipe_versions(data), "versions = [...] missing")
                for kind in ("code", "amx", "shader", "bxml", "text", "layout", "subs"):
                    for entry in data.get(kind, []):
                        self.assertLessEqual(set(entry.get("versions", [])), set(mod.recipe_versions(data) or []),
                                             f"[[{kind}]] versions not among the recipe's")
                for version in mod.recipe_versions(data) or []:
                    resolved = mod.for_version(data, version, recipe.parent.name)     # no value missing
                    for key, value in resolved.get("symbols", {}).items():
                        self.assertIs(type(value), int, f"[symbols] {key}")         # not a key of the recipe

    def test_build_for_a_version(self):
        """A mod that does not support the version is refused; a fix that does not is left aside."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "mods" / "fix").mkdir(parents=True)
            (root / "mods" / "fix" / "mod.toml").write_text('always = true\nversions = ["v0"]\n[[code]]\n'
                                                            'address = 0x100000\nbytes = "00"\n', encoding="utf-8")
            (root / "mods" / "old").mkdir()
            (root / "mods" / "old" / "mod.toml").write_text('name = "Old"\nversions = ["v0"]\n', encoding="utf-8")
            (root / "mods" / "any").mkdir()
            (root / "mods" / "any" / "mod.toml").write_text('name = "Any"\n', encoding="utf-8")
            game = root / "extracted"
            (game / "romfs").mkdir(parents=True)
            (game / "v5200" / "romfs").mkdir(parents=True)
            for code in (game / "code.bin", game / "v5200" / "code.bin"):
                code.write_bytes(bytes(16))
            with mock.patch.object(mod, "MODS", root / "mods"), mock.patch.object(versions, "EXTRACTED", game), \
                    mock.patch.object(mod, "project_version", return_value="v0.1"):
                with self.assertRaises(mod.ModError) as refused:
                    mod.build(["old"], root / "out", version="v5200")
                self.assertIn("v5200", str(refused.exception))
                built = mod.build(["any"], root / "out", version="v5200")
                self.assertEqual(built.name, "any-v5200")
                marker = json.loads((built / azahar.TITLE_ID / azahar.MARKER).read_text(encoding="utf-8"))
                self.assertEqual(marker["version"], "v5200")
                self.assertEqual(marker["mods"], ["any"])                  # the fix left aside
                built = mod.build(["any"], root / "out", version="v0")
                self.assertEqual(json.loads((built / azahar.TITLE_ID / azahar.MARKER).read_text())["mods"],
                                 ["fix", "any"])

    def test_fixes_always_included(self):
        self.assertEqual(mod.fixes(), ["correctifs", "pseudo", "version"])
        recipe = tomllib.loads((TOOLS.parent / "mods" / "correctifs" / "mod.toml").read_text(encoding="utf-8"))
        self.assertEqual({e["instruction"] for e in recipe["shader"]}, {0x061, 0x084})


HOLD_PORTS = """
import socket, sys, time
socks = []
for port in sys.argv[1].split(","):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", int(port)))
    socks.append(s)
print("ready", flush=True)
time.sleep(60)
"""


def free_udp_ports(count: int) -> list[int]:
    socks = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(count)]
    for s in socks:
        s.bind(("0.0.0.0", 0))
    ports = [s.getsockname()[1] for s in socks]
    for s in socks:
        s.close()
    return ports


class Launcher(unittest.TestCase):
    """« Lancer le serveur » stops a server started elsewhere that holds its ports, never another program."""

    def hold(self, ports: list[int], marker: str) -> subprocess.Popen:
        process = subprocess.Popen([sys.executable, "-c", HOLD_PORTS, ",".join(map(str, ports)), marker],
                                   stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (process.kill(), process.wait(), process.stdout.close()))
        self.assertEqual(process.stdout.readline().strip(), "ready")
        return process

    def test_stops_a_server_started_elsewhere(self):
        ports = free_udp_ports(2)
        process = self.hold(ports, "-m sdsw_server")
        if process.pid not in webui.udp_port_owners(set(ports)):
            self.skipTest("this system does not tell which process holds a port")
        server = webui.GameServer()
        with mock.patch.object(webui.GameServer, "ports", classmethod(lambda cls: ports)):
            self.assertEqual(list(server.others()), [process.pid])
            server.stop_others()
        self.assertIsNotNone(process.wait(5))
        self.assertEqual(webui.busy_udp_ports(ports), [])

    def test_never_stops_another_program(self):
        ports = free_udp_ports(1)
        process = self.hold(ports, "another-game")
        if process.pid not in webui.udp_port_owners(set(ports)):
            self.skipTest("this system does not tell which process holds a port")
        server = webui.GameServer()
        with mock.patch.object(webui.GameServer, "ports", classmethod(lambda cls: ports)):
            self.assertEqual(server.others(), {})
            with self.assertRaises(webui.UserError):
                server.stop_others()
            server.stop_others(strict=False)
        self.assertIsNone(process.poll())


if __name__ == "__main__":
    unittest.main()
