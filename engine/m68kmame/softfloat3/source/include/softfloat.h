// Stand-in for MAME's 3rdparty softfloat3 header: only the types m68kmusashi.h declares members of (the 68010 has
// no FPU; the FPU opcodes are never reached).  Not MAME code.
#pragma once
#include <cstdint>
typedef struct { uint64_t signif; uint16_t signExp; } extFloat80_t;
typedef struct { uint64_t v; } float64_t;
inline float64_t extF80_to_f64(extFloat80_t) { return float64_t{0}; }
inline extFloat80_t f64_to_extF80(float64_t) { return extFloat80_t{0, 0}; }
inline uint_fast8_t softfloat_roundingMode;
inline uint_fast8_t extF80_roundingPrecision;
