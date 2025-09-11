// #include <stdint.h> // int16_t, uint16_t, uint8_t 等
#include "../mystdint/stdint.h"

typedef enum {
    CarModeSuccess = 0,
    CarModeFailure = 1
} CarModeStatus;

typedef struct {
    CarModeStatus status;  // 成功/失败
    int16_t VehSpdabs;     // 绝对速度值，用于外层日志判断
} CarModeResult;

const int16_t SpeedCM_Value = 3;

/**
 * 核心判断函数：纯函数，无副作用
 */
CarModeResult SpeedjudgeAndCarmoderestore_CorePure(uint16_t VehSpd,
                                                   uint8_t VehSpdVld) {
    int16_t transformedVehSpd = (VehSpd / 100) - 200;

    int16_t _VehSpdabs;

    if (transformedVehSpd < 0) {
        _VehSpdabs = -transformedVehSpd;
    } else {
        _VehSpdabs = transformedVehSpd;
    }

    CarModeResult res;
    res.VehSpdabs = _VehSpdabs;

    if (_VehSpdabs < 3 && VehSpdVld == 1) {
        res.status = 0;
    } else {
        res.status = 1;
    }

    return res;
}
