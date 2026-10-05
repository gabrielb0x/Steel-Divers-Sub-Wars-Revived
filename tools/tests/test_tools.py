"""Tests of the players' tools that need no game file: ARM assembler, save format, recipes.

    python3 -m unittest discover -s tools/tests
"""

import struct
import sys
import tomllib
import unittest
import zlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))

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
    ('bxne r3', "13ff2f11"),
    ('blx r3', "33ff2fe1"),
    ('.word 0x1234', "34120000"),
    ('.word 1, 2, 3', "010000000200000003000000"),
    ('.short 5', "0500"),
    ('.byte 1, 2, 255', "0102ff"),
    ('.asciz "save.sub.unlock"', "736176652e7375622e756e6c6f636b00"),
    ('.ascii "abc"', "616263"),
    ('.align 2', ""),
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
            for entry in tomllib.loads(recipe.read_text(encoding="utf-8")).get("code", []):
                if "arm" in entry:
                    with self.subTest(recipe=recipe.parent.name, address=hex(entry["address"])):
                        code = assemble(Template(entry["arm"]).safe_substitute(params), entry["address"])
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

    def test_values(self):
        self.assertEqual(parse_value("0x10"), 16)
        self.assertEqual(parse_value("1,0,1"), [1, 0, 1])
        self.assertEqual(parse_value("1.5"), struct.unpack("<i", struct.pack("<f", 1.5))[0])
        with self.assertRaises(SaveError):
            SaveData().set("player.sub", 1)               # not saved by the game


if __name__ == "__main__":
    unittest.main()
