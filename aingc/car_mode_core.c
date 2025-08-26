#include <stdint.h> // int16_t, uint16_t, uint8_t 等


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

    int16_t VehSpdabs;

    if (transformedVehSpd < 0) {
        VehSpdabs = -transformedVehSpd;
    } else {
        VehSpdabs = transformedVehSpd;
    }

    CarModeResult res;
    res.VehSpdabs = VehSpdabs;

    if (VehSpdabs < 3 && VehSpdVld == 1) {
        res.status = 0;
    } else {
        res.status = 1;
    }

    return res;
}


int main() {
    // 示例代码

    //Car mode success 的例子
    uint16_t VehSpd = 20000;
    uint8_t VehSpdVld = 1;

    CarModeResult result = SpeedjudgeAndCarmoderestore_CorePure(VehSpd, VehSpdVld);

    if (result.status == 0) {
        printf("Car mode success\n");
    } else {
        printf("Car mode failure\n");
    }

    printf("Vehicle speed absolute value: %d\n", result.VehSpdabs);

    //Car mode failure 的例子
    uint16_t VehSpd = 12345;
    uint8_t VehSpdVld = 0;

    CarModeResult result = SpeedjudgeAndCarmoderestore_CorePure(VehSpd, VehSpdVld);

    if (result.status == 0) {
        printf("Car mode success\n");
    } else {
        printf("Car mode failure\n");
    }

    printf("Vehicle speed absolute value: %d\n", result.VehSpdabs);

    return 0;
}
