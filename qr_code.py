"""สร้าง QR Code แบบ byte mode (ระดับแก้ไขข้อผิดพลาด M) ด้วยไลบรารีมาตรฐาน

ใช้สำหรับแชร์ลิงก์หน้าโน้ตไปยังมือถือ โดยไม่ต้องติดตั้งแพ็กเกจเพิ่ม
รองรับเวอร์ชัน 1-6 (สูงสุด 108 ไบต์) ซึ่งเกินพอสำหรับ URL ในวง LAN
"""

from __future__ import annotations

import struct
import zlib

# เวอร์ชัน -> (โค้ดเวิร์ดข้อมูลรวม, โค้ดเวิร์ด ECC ต่อบล็อก, จำนวนบล็อก)
VERSION_SPECS: dict[int, tuple[int, int, int]] = {
    1: (16, 10, 1),
    2: (28, 16, 1),
    3: (44, 26, 1),
    4: (64, 18, 2),
    5: (86, 24, 2),
    6: (108, 16, 4),
}

# พิกัดกึ่งกลางของ alignment pattern ในแต่ละเวอร์ชัน
ALIGNMENT_CENTERS: dict[int, tuple[int, ...]] = {
    1: (),
    2: (6, 18),
    3: (6, 22),
    4: (6, 26),
    5: (6, 30),
    6: (6, 34),
}

FORMAT_MASK = 0b101010000010010
FORMAT_ECC_MEDIUM = 0b00
FINDER_RUN = (1, 0, 1, 1, 1, 0, 1)
QUIET_ZONE = 4

_EXPONENTIALS = [0] * 512
_LOGARITHMS = [0] * 256


def _build_galois_tables() -> None:
    value = 1
    for index in range(255):
        _EXPONENTIALS[index] = value
        _LOGARITHMS[value] = index
        value <<= 1
        if value & 0x100:
            value ^= 0x11D
    for index in range(255, 512):
        _EXPONENTIALS[index] = _EXPONENTIALS[index - 255]


_build_galois_tables()


def _multiply(left: int, right: int) -> int:
    if left == 0 or right == 0:
        return 0
    return _EXPONENTIALS[_LOGARITHMS[left] + _LOGARITHMS[right]]


def _generator_polynomial(degree: int) -> list[int]:
    polynomial = [1]
    for index in range(degree):
        product = [0] * (len(polynomial) + 1)
        for position, coefficient in enumerate(polynomial):
            product[position] ^= coefficient
            product[position + 1] ^= _multiply(coefficient, _EXPONENTIALS[index])
        polynomial = product
    return polynomial


def _error_correction(data: list[int], count: int) -> list[int]:
    generator = _generator_polynomial(count)
    remainder = list(data) + [0] * count
    for index in range(len(data)):
        factor = remainder[index]
        if factor == 0:
            continue
        for offset, coefficient in enumerate(generator):
            remainder[index + offset] ^= _multiply(coefficient, factor)
    return remainder[len(data) :]


def _pick_version(length: int) -> int:
    for version, (total_data, _, _) in VERSION_SPECS.items():
        # 4 บิตโหมด + 8 บิตความยาว + ข้อมูล ต้องไม่เกินความจุ
        if 12 + length * 8 <= total_data * 8:
            return version
    raise ValueError("ข้อความยาวเกินกว่าที่ QR Code เวอร์ชัน 6 รองรับ")


def _encode_codewords(payload: bytes, version: int) -> list[int]:
    total_data, ecc_count, block_count = VERSION_SPECS[version]
    bits: list[int] = []

    def push(value: int, length: int) -> None:
        for shift in range(length - 1, -1, -1):
            bits.append((value >> shift) & 1)

    push(0b0100, 4)
    push(len(payload), 8)
    for byte in payload:
        push(byte, 8)
    push(0, min(4, total_data * 8 - len(bits)))
    while len(bits) % 8:
        bits.append(0)

    codewords = [
        int("".join(str(bit) for bit in bits[index : index + 8]), 2)
        for index in range(0, len(bits), 8)
    ]
    padding = (0xEC, 0x11)
    pad_index = 0
    while len(codewords) < total_data:
        codewords.append(padding[pad_index % 2])
        pad_index += 1

    short_length = total_data // block_count
    long_blocks = total_data % block_count
    data_blocks: list[list[int]] = []
    cursor = 0
    for index in range(block_count):
        length = short_length + (1 if index >= block_count - long_blocks else 0)
        data_blocks.append(codewords[cursor : cursor + length])
        cursor += length
    ecc_blocks = [_error_correction(block, ecc_count) for block in data_blocks]

    interleaved: list[int] = []
    for position in range(max(len(block) for block in data_blocks)):
        for block in data_blocks:
            if position < len(block):
                interleaved.append(block[position])
    for position in range(ecc_count):
        for block in ecc_blocks:
            interleaved.append(block[position])
    return interleaved


def _place_function_patterns(
    matrix: list[list[int | None]],
    reserved: list[list[bool]],
    version: int,
) -> None:
    size = len(matrix)

    def paint(row: int, column: int, dark: int) -> None:
        if 0 <= row < size and 0 <= column < size:
            matrix[row][column] = dark
            reserved[row][column] = True

    for origin_row, origin_column in ((0, 0), (0, size - 7), (size - 7, 0)):
        for row in range(-1, 8):
            for column in range(-1, 8):
                inside = 0 <= row < 7 and 0 <= column < 7
                dark = inside and (
                    row in (0, 6)
                    or column in (0, 6)
                    or (2 <= row <= 4 and 2 <= column <= 4)
                )
                paint(origin_row + row, origin_column + column, 1 if dark else 0)

    for index in range(8, size - 8):
        timing = 1 if index % 2 == 0 else 0
        paint(6, index, timing)
        paint(index, 6, timing)

    centers = ALIGNMENT_CENTERS[version]
    for center_row in centers:
        for center_column in centers:
            if reserved[center_row][center_column]:
                continue
            for row in range(-2, 3):
                for column in range(-2, 3):
                    ring = max(abs(row), abs(column))
                    paint(
                        center_row + row,
                        center_column + column,
                        0 if ring == 1 else 1,
                    )

    paint(size - 8, 8, 1)
    for index in range(9):
        if not reserved[8][index]:
            paint(8, index, 0)
        if not reserved[index][8]:
            paint(index, 8, 0)
    for index in range(8):
        if not reserved[8][size - 1 - index]:
            paint(8, size - 1 - index, 0)
        if not reserved[size - 1 - index][8]:
            paint(size - 1 - index, 8, 0)


def _place_codewords(
    matrix: list[list[int | None]],
    reserved: list[list[bool]],
    codewords: list[int],
) -> None:
    size = len(matrix)
    cursor = 0
    total_bits = len(codewords) * 8
    right = size - 1
    while right > 0:
        if right == 6:
            right = 5
        for step in range(size):
            for offset in range(2):
                column = right - offset
                upward = ((right + 1) & 2) == 0
                row = (size - 1 - step) if upward else step
                if reserved[row][column] or cursor >= total_bits:
                    continue
                bit = (codewords[cursor >> 3] >> (7 - (cursor & 7))) & 1
                matrix[row][column] = bit
                cursor += 1
        right -= 2


def _mask_bit(pattern: int, row: int, column: int) -> bool:
    if pattern == 0:
        return (row + column) % 2 == 0
    if pattern == 1:
        return row % 2 == 0
    if pattern == 2:
        return column % 3 == 0
    if pattern == 3:
        return (row + column) % 3 == 0
    if pattern == 4:
        return (row // 2 + column // 3) % 2 == 0
    if pattern == 5:
        return (row * column) % 2 + (row * column) % 3 == 0
    if pattern == 6:
        return ((row * column) % 2 + (row * column) % 3) % 2 == 0
    return ((row + column) % 2 + (row * column) % 3) % 2 == 0


def _format_bits(mask: int) -> int:
    data = (FORMAT_ECC_MEDIUM << 3) | mask
    remainder = data
    for _ in range(10):
        remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
    return ((data << 10) | remainder) ^ FORMAT_MASK


def _place_format(matrix: list[list[int]], mask: int) -> None:
    size = len(matrix)
    bits = _format_bits(mask)

    def bit_at(index: int) -> int:
        return (bits >> index) & 1

    for index in range(6):
        matrix[index][8] = bit_at(index)
    matrix[7][8] = bit_at(6)
    matrix[8][8] = bit_at(7)
    matrix[8][7] = bit_at(8)
    for index in range(9, 15):
        matrix[8][14 - index] = bit_at(index)
    for index in range(8):
        matrix[8][size - 1 - index] = bit_at(index)
    for index in range(8, 15):
        matrix[size - 15 + index][8] = bit_at(index)
    matrix[size - 8][8] = 1


def _line_penalty(line: list[int]) -> int:
    penalty = 0
    run_value = line[0]
    run_length = 1
    for value in line[1:]:
        if value == run_value:
            run_length += 1
            continue
        if run_length >= 5:
            penalty += 3 + run_length - 5
        run_value = value
        run_length = 1
    if run_length >= 5:
        penalty += 3 + run_length - 5
    for start in range(len(line) - 10):
        window = tuple(line[start : start + 11])
        if window == FINDER_RUN + (0, 0, 0, 0):
            penalty += 40
        if window == (0, 0, 0, 0) + FINDER_RUN:
            penalty += 40
    return penalty


def _penalty(matrix: list[list[int]]) -> int:
    size = len(matrix)
    score = 0
    for row in range(size):
        score += _line_penalty(matrix[row])
        score += _line_penalty([matrix[index][row] for index in range(size)])
    for row in range(size - 1):
        for column in range(size - 1):
            block = (
                matrix[row][column]
                + matrix[row][column + 1]
                + matrix[row + 1][column]
                + matrix[row + 1][column + 1]
            )
            if block in (0, 4):
                score += 3
    dark = sum(sum(line) for line in matrix)
    percent = dark * 100 / (size * size)
    score += 10 * (int(abs(percent - 50) / 5))
    return score


def qr_matrix(text: str) -> list[list[int]]:
    """คืนตารางโมดูล QR (1 = ทึบ, 0 = โปร่ง) ของข้อความที่ส่งเข้ามา"""
    payload = text.encode("utf-8")
    version = _pick_version(len(payload))
    size = 17 + 4 * version
    codewords = _encode_codewords(payload, version)

    base: list[list[int | None]] = [[None] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]
    _place_function_patterns(base, reserved, version)
    _place_codewords(base, reserved, codewords)
    filled = [[int(value or 0) for value in line] for line in base]

    best: list[list[int]] | None = None
    best_score = 0
    for mask in range(8):
        candidate = [list(line) for line in filled]
        for row in range(size):
            for column in range(size):
                if not reserved[row][column] and _mask_bit(mask, row, column):
                    candidate[row][column] ^= 1
        _place_format(candidate, mask)
        score = _penalty(candidate)
        if best is None or score < best_score:
            best = candidate
            best_score = score
    assert best is not None
    return best


def qr_png(text: str, *, scale: int = 8, quiet: int = QUIET_ZONE) -> bytes:
    """คืนไฟล์ PNG ขาวดำของ QR Code สำหรับข้อความที่ส่งเข้ามา"""
    matrix = qr_matrix(text)
    size = len(matrix)
    width = (size + quiet * 2) * scale
    blank_row = bytes([255]) * width

    raw = bytearray()
    for _ in range(quiet * scale):
        raw.append(0)
        raw.extend(blank_row)
    for line in matrix:
        pixels = bytearray(bytes([255]) * (quiet * scale))
        for value in line:
            pixels.extend(bytes([0 if value else 255]) * scale)
        pixels.extend(bytes([255]) * (quiet * scale))
        for _ in range(scale):
            raw.append(0)
            raw.extend(pixels)
    for _ in range(quiet * scale):
        raw.append(0)
        raw.extend(blank_row)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, width, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
