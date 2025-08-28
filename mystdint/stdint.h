#ifndef __FAKE_STDINT_H__
#define __FAKE_STDINT_H__

// 有符号整数
typedef signed char         int8_t;
typedef signed short int    int16_t;
typedef signed int          int32_t;
typedef signed long long    int64_t;

// 无符号整数
typedef unsigned char       uint8_t;
typedef unsigned short int  uint16_t;
typedef unsigned int        uint32_t;
typedef unsigned long long  uint64_t;

typedef _Bool bool;
#define true 1
#define false 0

#endif /* __FAKE_STDINT_H__ */
