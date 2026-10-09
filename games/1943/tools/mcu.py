"""Execute the 1943 i8751 firmware at reset and on VBL INT1.

Transactions are instruction-exact but synchronous, not cycle accurate.
Only firmware-used instructions are supported; unknown instructions fail.
"""
class MCU:
    def __init__(self, rom):
        self.rom = bytes(rom)
        self.ram = bytearray(256)
        self.ram[0x81] = 7
        for addr in (0x80, 0x90, 0xa0, 0xb0):
            self.ram[addr] = 255
        self.pc = 0
        self.command = self.response = 0
        self.active = False
        self.transactions = 0
        self.run()

    def fetch(self):
        value = self.rom[self.pc]
        self.pc += 1
        return value

    def reg(self, index):
        return (self.ram[0xd0] & 0x18) + index

    def read(self, addr):
        return self.command & self.ram[0x80] if addr == 0x80 else self.ram[addr]

    def write(self, addr, value):
        value &= 255
        old = self.ram[addr]
        self.ram[addr] = value
        if addr == 0xb0 and old & 64 and not value & 64:
            self.response = self.ram[0x80]
            self.transactions += 1

    def relative(self, offset):
        self.pc += (offset ^ 128) - 128

    def push(self, value):
        self.ram[0x81] = (self.ram[0x81] + 1) & 255
        self.ram[self.ram[0x81]] = value

    def pop(self):
        value = self.ram[self.ram[0x81]]
        self.ram[0x81] = (self.ram[0x81] - 1) & 255
        return value

    def run(self):
        for _ in range(4096):
            pc, op = self.pc, self.fetch()
            if op == 0: pass
            elif op == 2:
                hi, lo = self.fetch(), self.fetch()
                self.pc = hi*256+lo
            elif op == 0x75:
                addr, value = self.fetch(), self.fetch()
                self.write(addr, value)
            elif 0x78 <= op <= 0x7f:
                self.ram[self.reg(op & 7)] = self.fetch()
            elif op == 0x74: self.write(0xe0, self.fetch())
            elif op in (0xf6, 0xf7): self.ram[self.ram[self.reg(op & 1)]] = self.ram[0xe0]
            elif op == 0xf5: self.write(self.fetch(), self.ram[0xe0])
            elif op == 0xe4: self.write(0xe0, 0)
            elif 0xe8 <= op <= 0xef: self.write(0xe0, self.ram[self.reg(op & 7)])
            elif 0xf8 <= op <= 0xff: self.ram[self.reg(op & 7)] = self.ram[0xe0]
            elif op == 0xe5: self.write(0xe0, self.read(self.fetch()))
            elif 0xa8 <= op <= 0xaf: self.ram[self.reg(op & 7)] = self.read(self.fetch())
            elif 0x88 <= op <= 0x8f: self.write(self.fetch(), self.ram[self.reg(op & 7)])
            elif op in (0xc2, 0xd2):
                bit = self.fetch()
                addr = bit & 0xf8 if bit >= 128 else 0x20 + bit//8
                mask = 1 << (bit & 7)
                self.write(addr, self.ram[addr] | mask if op == 0xd2 else self.ram[addr] & ~mask)
            elif op == 0x53:
                addr, value = self.fetch(), self.fetch()
                self.write(addr, self.ram[addr] & value)
            elif op == 0xc3: self.ram[0xd0] &= 127
            elif op == 0x05:
                addr = self.fetch()
                self.write(addr, self.ram[addr]+1)
            elif op == 0x93:
                dptr = self.ram[0x83]*256+self.ram[0x82]
                self.write(0xe0, self.rom[dptr+self.ram[0xe0]])
            elif op == 0x9a:
                a, b = self.ram[0xe0], self.ram[self.reg(2)]
                carry = self.ram[0xd0] >> 7
                result = a-b-carry
                psw = self.ram[0xd0] & ~0xc4
                psw |= (int(result < 0) << 7) | (int((a & 15) < (b & 15)+carry) << 6)
                psw |= int(bool((a ^ b) & (a ^ result) & 128)) << 2
                self.ram[0xd0] = psw
                self.write(0xe0, result)
            elif op == 0x70:
                offset = self.fetch()
                if self.ram[0xe0]: self.relative(offset)
            elif 0xd8 <= op <= 0xdf:
                offset = self.fetch()
                addr = self.reg(op & 7)
                self.ram[addr] = (self.ram[addr]-1) & 255
                if self.ram[addr]: self.relative(offset)
            elif op == 0x80:
                self.relative(self.fetch())
                if self.pc == pc: return
            elif op == 0x32:
                hi, lo = self.pop(), self.pop()
                self.pc = hi*256+lo
                self.active = False
            else: raise NotImplementedError(f'i8751 opcode {op:02x} at {pc:04x}')
            # 8051 parity reflects ACC after every instruction.
            self.ram[0xd0] = (self.ram[0xd0] & 254) | (self.ram[0xe0].bit_count() & 1)
        raise RuntimeError('i8751 did not return to idle')

    def vblank(self):
        if self.active or self.ram[0xa8] & 0x84 != 0x84:
            raise RuntimeError('i8751 INT1 not enabled')
        self.push(self.pc & 255)
        self.push(self.pc >> 8)
        self.pc = 0x13
        self.active = True
        self.run()
        return self.response
