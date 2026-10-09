"""Firmware interpreter for the opcodes used by Black Tiger's dumped i8751.

Runs reset and INT1 to the firmware's idle loop; unknown opcodes fail explicitly.
Command transactions complete synchronously (instruction timing is not modelled).
"""
class MCU:
    def __init__(self, rom):
        self.rom = bytes(rom)
        self.ram = bytearray(256)
        self.ram[0x81] = 7
        for a in (0x80, 0x90, 0xa0, 0xb0):
            self.ram[a] = 255
        self.pc = 0
        self.command = self.response = 0
        self.active = False
        self.run()

    def fetch(self):
        v = self.rom[self.pc]
        self.pc += 1
        return v

    def push(self, v):
        self.ram[0x81] += 1
        self.ram[self.ram[0x81]] = v

    def pop(self):
        v = self.ram[self.ram[0x81]]
        self.ram[0x81] -= 1
        return v

    def write(self, addr, v):
        self.ram[addr] = v
        if addr == 0x80:
            self.response = v

    def run(self):
        for _ in range(4096):
            pc = self.pc
            op = self.fetch()
            if op == 0x02:  # LJMP
                hi, lo = self.fetch(), self.fetch()
                self.pc = hi * 256 + lo
            elif op == 0x75:  # MOV direct,#imm
                addr, v = self.fetch(), self.fetch()
                self.write(addr, v)
            elif op == 0x78:
                self.ram[0] = self.fetch()
            elif op == 0x74:
                self.ram[0xe0] = self.fetch()
            elif op == 0xf6:
                self.ram[self.ram[0]] = self.ram[0xe0]
            elif op == 0xd8:
                off = self.fetch()
                self.ram[0] = (self.ram[0] - 1) & 255
                if self.ram[0]:
                    self.pc += (off ^ 128) - 128
            elif op in (0xc2, 0xd2):
                bit = self.fetch()
                addr = (bit & 0xf8) if bit >= 128 else 0x20 + bit // 8
                mask = 1 << (bit & 7)
                v = self.ram[addr]
                self.write(addr, v | mask if op == 0xd2 else v & ~mask)
            elif op == 0x80:
                off = self.fetch()
                self.pc += (off ^ 128) - 128
                if self.pc == pc:
                    return
            elif op == 0xe5:
                addr = self.fetch()
                self.ram[0xe0] = self.command if addr == 0x80 else self.ram[addr]
            elif op == 0x54:
                self.ram[0xe0] &= self.fetch()
            elif op == 0x90:
                self.ram[0x83], self.ram[0x82] = self.fetch(), self.fetch()
            elif op == 0x93:
                dptr = self.ram[0x83] * 256 + self.ram[0x82]
                self.ram[0xe0] = self.rom[dptr + self.ram[0xe0]]
            elif op == 0xf5:
                self.write(self.fetch(), self.ram[0xe0])
            elif op == 0x32:
                hi, lo = self.pop(), self.pop()
                self.pc = hi * 256 + lo
                self.active = False
            else:
                raise NotImplementedError(f"i8751 opcode {op:02x} at {pc:04x}")
        raise RuntimeError("i8751 did not return to idle")

    def send(self, command):
        if self.active or self.ram[0xa8] & 0x84 != 0x84:
            raise RuntimeError("i8751 INT1 not ready")
        self.command = command
        self.push(self.pc & 255)
        self.push(self.pc >> 8)
        self.pc = 0x13
        self.active = True
        self.run()
        return self.response
