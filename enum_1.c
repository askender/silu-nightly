#include <stdbool.h>
#include <stdio.h>

typedef enum {
    PS_enum_CarModes_Factory = 0,
    PS_enum_CarModes_Normal = 1,
    PS_enum_CarModes_Exihibition = 2,
    PS_enum_CarModes_Crash = 3,
    PS_enum_CarModes_Transport = 4
} PS_enum_CarModes;

int main() {
    PS_enum_CarModes mode = PS_enum_CarModes_Normal;
    printf("Normal: Current mode: %d\n", mode);
    return 0;
}
