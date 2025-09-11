// #include <stdbool.h>
#include "../mystdint/stdint.h"
#include <stdio.h>

typedef enum {
    PS_enum_CarModes_Factory = 0,
    PS_enum_CarModes_Normal = 1,
    PS_enum_CarModes_Exihibition = 2,
    PS_enum_CarModes_Crash = 3,
    PS_enum_CarModes_Transport = 4
} PS_enum_CarModes;

PS_enum_CarModes PS_VC_CarMode_DecideNewMode(
    PS_enum_CarModes currentMode,
    unsigned char acu_crashOutputSts1,
    unsigned char acu_crashOutputSts1_last,
    unsigned char acu_crashOutputSts1Valid
)
{
    bool isAcu_Crashappen = false;

    // 判断是否发生 Crash
    if (((acu_crashOutputSts1_last == 0) || (acu_crashOutputSts1_last == 1)) &&
        ((acu_crashOutputSts1 == 2) || (acu_crashOutputSts1 == 3)))
    {
        isAcu_Crashappen = true;
    }

    // 根据当前模式和 Crash 状态决定新的模式
    switch (currentMode)
    {
        case PS_enum_CarModes_Normal:
            if (isAcu_Crashappen && (acu_crashOutputSts1Valid == 1))
            {
                return PS_enum_CarModes_Crash;
            }
            break;

        case PS_enum_CarModes_Factory:
        case PS_enum_CarModes_Exihibition:
        case PS_enum_CarModes_Crash:
        case PS_enum_CarModes_Transport:
        default:
            break;
    }

    return currentMode; // 未发生切换
}
