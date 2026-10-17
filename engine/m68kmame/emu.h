// The part of MAME's emulator framework that MAME 0.289's Musashi core (src/devices/cpu/m68000/m68kmusashi.h,
// m68kcpu.h, m68kmmu.h and the generated m68kops.cpp) needs to compile outside MAME: the types, a cpu_device base
// with the virtual functions the core overrides, and memory accessors that call the board (glue.cpp).
// Not MAME code; written for engine/m68kmame.py.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <memory>
#include <string>
#include <vector>
#include <utility>

typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
typedef int8_t s8; typedef int16_t s16; typedef int32_t s32; typedef int64_t s64;
typedef u32 offs_t;

#define ATTR_COLD
#define WORD_ALIGNED(a) (((a) & 1) == 0)
enum { CLEAR_LINE = 0, ASSERT_LINE = 1, INPUT_LINE_NMI = 32 };
enum { AS_PROGRAM = 0, AS_DATA = 1, AS_IO = 2, AS_OPCODES = 3 };
#define NAME(x) x, #x
#define STRUCT_MEMBER(s, m) s, #m
#define STATE_GENPC (-1)
enum endianness_t { ENDIANNESS_LITTLE, ENDIANNESS_BIG };
template <typename T, typename U> constexpr T make_bitmask(U n) { return T((n < (8 * sizeof(T)) ? (std::make_unsigned_t<T>(1) << n) : std::make_unsigned_t<T>(0)) - 1); }
template <typename... Ts> inline void logerror(const char *, Ts...) { }
template <typename... Ts> [[noreturn]] inline void fatalerror(const char *fmt, Ts... args) { std::fprintf(stderr, fmt, args...); std::abort(); }

// the board's memory (glue.cpp)
u16 glue_read_word(offs_t a, u16 mask);
void glue_write_word(offs_t a, u16 data, u16 mask);
u16 glue_read_imm(offs_t a);
u16 glue_cpu_space_read(offs_t a);
void glue_reset_out(int state);
void glue_irq_ack(int level);

class device_t;
class machine_config;
typedef const void *device_type;
class address_map;
typedef std::function<void (address_map &)> address_map_constructor;
namespace util { class disasm_interface { public: virtual ~disasm_interface() { } }; }
class device_state_entry { public: int index() const { return 0; } };

struct address_space_config {
	address_space_config(const char *, endianness_t, int, int addrwidth, int = 0, address_map_constructor = nullptr) : m_addr_width(addrwidth) { }
	int addr_width() const { return m_addr_width; }
	int m_addr_width;
};

template <int Width, int AddrShift, int Level, endianness_t Endian> struct memory_access {
	struct cache {
		u8 read_byte(offs_t a) { return (glue_read_imm(a & ~1) >> (a & 1 ? 0 : 8)) & 0xff; }
		u16 read_word(offs_t a) { return glue_read_imm(a); }
		u32 read_dword(offs_t a) { u32 h = glue_read_imm(a); return (h << 16) | glue_read_imm(a + 2); }
	};
	struct specific {
		u8 read_byte(offs_t a) { return (glue_read_word(a & ~1, a & 1 ? 0x00ff : 0xff00) >> (a & 1 ? 0 : 8)) & 0xff; }
		u16 read_word(offs_t a) { return glue_read_word(a, 0xffff); }
		u16 read_word(offs_t a, u16 mask) { return glue_read_word(a, mask); }
		u32 read_dword(offs_t a) { u32 h = glue_read_word(a, 0xffff); return (h << 16) | glue_read_word(a + 2, 0xffff); }
		void write_byte(offs_t a, u8 d) { glue_write_word(a & ~1, d | (d << 8), a & 1 ? 0x00ff : 0xff00); }
		void write_word(offs_t a, u16 d) { glue_write_word(a, d, 0xffff); }
		void write_word(offs_t a, u16 d, u16 mask) { glue_write_word(a, d, mask); }
		void write_dword(offs_t a, u32 d) { glue_write_word(a, d >> 16, 0xffff); glue_write_word(a + 2, d & 0xffff, 0xffff); }
	};
};

class address_space {
public:
	u32 read_dword(offs_t a) { u32 h = glue_read_word(a, 0xffff); return (h << 16) | glue_read_word(a + 2, 0xffff); }
	void write_dword(offs_t a, u32 d) { glue_write_word(a, d >> 16, 0xffff); glue_write_word(a + 2, d & 0xffff, 0xffff); }
	u16 read_word(offs_t a, u16 = 0xffff) { return glue_cpu_space_read(a); }
	u8 read_byte(offs_t a) { return glue_cpu_space_read(a & ~1) >> (a & 1 ? 0 : 8); }
	template <typename T> void cache(T &) { }
	template <typename T> void specific(T &) { }
};

class running_machine { public: bool side_effects_disabled() const { return false; } };

class devcb_write_line {
public:
	devcb_write_line(device_t &) { }
	void operator()(int state) { glue_reset_out(state); }
	devcb_write_line &bind() { return *this; }
};

class cpu_device {
public:
	typedef std::vector<std::pair<int, const address_space_config *>> space_config_vector;
	cpu_device(const machine_config &, device_type, const char *, device_t *, u32) { }
	virtual ~cpu_device() { }
	const char *tag() const { return "maincpu"; }
	running_machine &machine() { static running_machine m; return m; }
	address_space &space(int) { static address_space s; return s; }
	bool has_space(int) const { return false; }
	bool has_configured_map(int) const { return false; }
	operator device_t &() { return *reinterpret_cast<device_t *>(this); }
protected:
	virtual u32 execute_min_cycles() const noexcept { return 1; }
	virtual u32 execute_max_cycles() const noexcept { return 1; }
	virtual void execute_run() { }
	virtual void execute_set_input(int, int) { }
	virtual bool execute_input_edge_triggered(int) const noexcept { return false; }
	virtual void device_start() { }
	virtual void device_reset() { }
	virtual void device_stop() { }
	virtual void device_pre_save() { }
	virtual void device_post_load() { }
	virtual space_config_vector memory_space_config() const { return {}; }
	virtual void state_import(const device_state_entry &) { }
	virtual void state_export(const device_state_entry &) { }
	virtual void state_string_export(const device_state_entry &, std::string &) const { }
	virtual bool memory_translate(int, int, offs_t &, address_space *&) { return true; }
	virtual std::unique_ptr<util::disasm_interface> create_disassembler() { return nullptr; }
	void debugger_instruction_hook(offs_t pc);
	void debugger_exception_hook(int) { }
	void debugger_privilege_hook() { }
	void debugger_wait_hook() { }
	int standard_irq_callback(int level, offs_t) { glue_irq_ack(level); return 0; }
	template <typename T> void save_item(T &&, const char *) { }
	template <typename T> void save_item(T &, const char *) { }
	void set_icountptr(int &) { }
};
