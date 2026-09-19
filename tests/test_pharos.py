"""Checks the reimplemented wire formats against what the vendor client emits.

Run with: python3 -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import eprint_pharos as p


class TestPacketFraming(unittest.TestCase):
    def test_header_length_is_19(self):
        self.assertEqual(p.HEADER_LEN, 19)

    def test_encode_matches_observed_request(self):
        # Byte-for-byte what the client sends for a bare GETPUBLICKEY.
        self.assertEqual(
            p.PopupServerClient.encode(["GETPUBLICKEY"]),
            b"PSPOPUP1003\x0c000032\x0cGETPUBLICKEY\x0c",
        )

    def test_length_counts_header_and_body(self):
        pkt = p.PopupServerClient.encode(["A", "BB"])
        self.assertEqual(int(pkt[12:18]), len(pkt))

    def test_separator_is_form_feed(self):
        self.assertEqual(p.SEP, b"\x0c")


class TestRC4(unittest.TestCase):
    def test_matches_published_vector(self):
        # RFC 6229 / classic test vector.
        self.assertEqual(p.rc4(b"Key", b"Plaintext").hex(), "bbf316e8d940af0ad3")

    def test_involutive(self):
        data = bytes(range(256)) * 3
        self.assertEqual(p.rc4(p.POPUP_RC4_KEY, p.rc4(p.POPUP_RC4_KEY, data)), data)

    def test_key_is_the_vendor_constant(self):
        self.assertEqual(p.POPUP_RC4_KEY.hex(), "4295f2a7680511b4c37439e1d2665794")


class TestSignatureBlock(unittest.TestCase):
    def test_is_32_bytes(self):
        self.assertEqual(len(p.signature_block(1, 2, 3)), 32)

    def test_field_offsets(self):
        b = p.signature_block(1234567, 111, 222)
        self.assertEqual(b[0:8].hex(), "c0c1c2c3c4c5c6c7")
        self.assertEqual(b[8:15], b"1234567")
        self.assertEqual(b[15:16], b"\x00")
        self.assertEqual(b[16:20], b"154\x00")
        self.assertEqual(b[20:25], b"00111")
        self.assertEqual(b[25:26], b"\x00")
        self.assertEqual(b[26:31], b"00222")
        self.assertEqual(b[31:32], b"\x00")

    def test_numbers_are_zero_padded(self):
        b = p.signature_block(0, 0, 0)
        self.assertEqual(b[8:15], b"0000000")
        self.assertEqual(b[20:25], b"00000")


class TestBlockSections(unittest.TestCase):
    def test_job_data_is_four_nul_terminated_strings(self):
        self.assertEqual(
            p.job_data_block("box", "abc123", "report.pdf", 2),
            b"box\x00abc123\x00report.pdf\x002\x00",
        )

    def test_answer_block_name_then_answer(self):
        desc = [{"name": "Username", "type": "String", "answer": "abc123",
                 "hierarchy_level": ""}]
        self.assertEqual(p.answer_block(desc), b"Username\x00abc123\x00")

    def test_answer_block_empty_answer_still_terminates(self):
        desc = [{"name": "Username", "type": "String", "answer": "",
                 "hierarchy_level": ""}]
        self.assertEqual(p.answer_block(desc), b"Username\x00\x00")

    def test_answer_block_skips_unanswered_guest(self):
        desc = [{"name": "Guest", "type": "Guest", "answer": "",
                 "hierarchy_level": ""}]
        self.assertEqual(p.answer_block(desc), b"")

    def test_answer_block_hierarchy_uses_cc_static(self):
        desc = [{"name": "Dept", "type": "CostCenter", "answer": "42",
                 "hierarchy_level": "1"}]
        self.assertEqual(p.answer_block(desc), b"CC_Static\x001\r42\x00")

    def test_xml_block_has_no_trailing_nul(self):
        b = p.xml_properties_block("cups", 3, 2)
        self.assertFalse(b.endswith(b"\x00"))
        self.assertIn(b"<AppTrackerPages>3</AppTrackerPages>", b)
        self.assertIn(b"<AppTrackerCopies>2</AppTrackerCopies>", b)
        self.assertTrue(b.startswith(b"<AppTrackerJob>\n<ProcessExecutable>cups"))


class TestPopupBlock(unittest.TestCase):
    def setUp(self):
        self.desc = [{"name": "Username", "type": "String", "answer": "abc123",
                      "hierarchy_level": ""}]
        self.block = p.build_popup_block("box", "abc123", "report.pdf", self.desc,
                                         application="cups", sides_imaged=1, copies=1)

    def test_starts_with_signature(self):
        self.assertEqual(self.block[:8].hex(), "c0c1c2c3c4c5c6c7")

    def test_declared_length_matches_ciphertext(self):
        self.assertEqual(int(self.block[8:15]), len(self.block) - 32)

    def test_sections_sum_to_total(self):
        total = int(self.block[8:15])
        s23 = int(self.block[20:25])
        s4 = int(self.block[26:31])
        self.assertEqual(s23 + s4, total)

    def test_body_decrypts_to_expected_layout(self):
        body = p.rc4(p.POPUP_RC4_KEY, self.block[32:])
        s23 = int(self.block[20:25])
        self.assertEqual(body[:s23],
                         b"box\x00abc123\x00report.pdf\x001\x00Username\x00abc123\x00")
        self.assertTrue(body[s23:].startswith(b"<AppTrackerJob>"))
        self.assertTrue(body.endswith(b"</AppTrackerJob>"))

    def test_section4_length_is_the_xml(self):
        s4 = int(self.block[26:31])
        self.assertEqual(s4, len(p.xml_properties_block("cups", 1, 1)))


class TestNotRsa(unittest.TestCase):
    def test_pads_only_when_leading_byte_is_00_or_01(self):
        self.assertEqual(p.not_rsa_pad(b"\x00ab"), b"\x01\x00ab")
        self.assertEqual(p.not_rsa_pad(b"\x01ab"), b"\x01\x01ab")
        self.assertEqual(p.not_rsa_pad(b"\x02ab"), b"\x02ab")

    def test_encrypt_is_textbook_modexp(self):
        # n = 3233, e = 17 is the classic toy RSA key.
        self.assertEqual(p.not_rsa_encrypt(b"\x41", "CA1", "11"),
                         "%X" % pow(0x41, 17, 0xCA1))


if __name__ == "__main__":
    unittest.main()
