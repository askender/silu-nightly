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

// input: acu_crashOutputSts1 =2/3  acu_crashOutputSts1Valid =1  gcarMode=1 output:gcarMode =3
// input: acu_crashOutputSts1 =2/3  acu_crashOutputSts1Valid =0  gcarMode=1 output:gcarMode =1
// input: acu_crashOutputSts1 =2/3  acu_crashOutputSts1Valid =0  gcarMode=3 output:gcarMode =3
int main(void)
{
    PS_enum_CarModes result = PS_VC_CarMode_DecideNewMode(
        PS_enum_CarModes_Normal,
        2, 0, 1
    );
    printf("Result: %d should be 3\n", result);


    PS_enum_CarModes result2 = PS_VC_CarMode_DecideNewMode(
        PS_enum_CarModes_Normal,
        2, 0, 0
    );
    printf("Result: %d should be 1\n", result2);

    PS_enum_CarModes result3 = PS_VC_CarMode_DecideNewMode(
        PS_enum_CarModes_Crash,
        2, 0, 0
    );
    printf("Result: %d should be 3\n", result3);

    PS_enum_CarModes result4 = PS_VC_CarMode_DecideNewMode(
        PS_enum_CarModes_Normal,
        2, 2, 1
    );
    printf("Result: %d should be ?\n", result4);

    PS_enum_CarModes result5 = PS_VC_CarMode_DecideNewMode(
        PS_enum_CarModes_Crash,
        2, 2, 1
    );
    printf("Result: %d should be ?\n", result5);


    return 0;
}
